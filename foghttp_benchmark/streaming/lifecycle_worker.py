__all__ = ("main", "run_lifecycle_worker")

import argparse
import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
import gc
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import TypeVar, cast
from urllib.parse import urlencode
import uuid

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.provenance import package_sources, research_provenance_from_env
from foghttp_benchmark.streaming.attribution_measure import measure_async_batch
from foghttp_benchmark.streaming.attribution_payloads import AttributionBatch
from foghttp_benchmark.streaming.clients import available_streaming_clients
from foghttp_benchmark.streaming.lifecycle_consume import (
    LifecycleStreamSample,
    async_client,
    consume_async_stream,
    consume_sync_stream,
    expected_body_digest,
    sync_client,
)
from foghttp_benchmark.streaming.lifecycle_controls import (
    UnsettledWorkers,
    control_json,
    run_async_controls,
    run_sync_controls,
    wait_quiet,
)
from foghttp_benchmark.streaming.lifecycle_models import (
    LifecycleCase,
    LifecycleConfig,
    lifecycle_config_from_payload,
    validate_lifecycle_case,
    validate_lifecycle_config,
)
from foghttp_benchmark.streaming.models import (
    AsyncStreamingAdapter,
    StreamingClientConfig,
    StreamingClientSpec,
    SyncStreamingAdapter,
)
from foghttp_benchmark.streaming.python_profile import active_python_instrumentation


def _high_water() -> JsonObject:
    if sys.platform not in {"darwin", "linux"}:
        return {"lifetime_high_water_rss_bytes": None, "high_water_unavailable_reason": "Unsupported ru_maxrss units"}
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "lifetime_high_water_rss_bytes": int(raw) * (1024 if sys.platform == "linux" else 1),
        "high_water_unavailable_reason": None,
        "high_water_scope": "client process lifetime; never substituted for current or sampled RSS",
    }


@dataclass(slots=True)
class _Worker:
    case: LifecycleCase
    config: LifecycleConfig
    base_url: str
    control_dir: Path
    output: Path
    report: JsonObject = field(default_factory=dict)
    phases: list[JsonObject] = field(default_factory=list)
    errors: list[JsonObject] = field(default_factory=list)
    stats: JsonObject = field(default_factory=dict)

    def save(self) -> None:
        self.report.update({"phases": self.phases, "errors": self.errors, "client_stats": self.stats})
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_suffix(self.output.suffix + ".tmp")
        temporary.write_text(json.dumps(self.report, indent=2) + "\n")
        temporary.replace(self.output)

    def mark(self, phase: str) -> None:
        marker: JsonObject = {"sequence": len(self.phases) + 1, "phase": phase, **_high_water()}
        temporary = self.control_dir / "marker.tmp"
        temporary.write_text(json.dumps(marker))
        temporary.replace(self.control_dir / "marker.json")
        deadline = time.monotonic() + self.config.settle_timeout_s
        while True:
            ack = self.control_dir / "ack.json"
            try:
                acknowledged = json.loads(ack.read_text()).get("sequence") == marker["sequence"]
            except FileNotFoundError:
                acknowledged = False
            if acknowledged:
                self.phases.append(marker)
                self.save()
                return
            if time.monotonic() >= deadline:
                msg = f"Parent did not acknowledge lifecycle phase {phase}"
                raise TimeoutError(msg)
            time.sleep(0.005)

    def observe(self, phase: str, adapter: AsyncStreamingAdapter | SyncStreamingAdapter) -> None:
        self.stats[phase] = adapter.stats()
        self.mark(phase)

    def observe_closed(self) -> None:
        self.stats["after_client_close"] = None
        self.report["after_close_stats_unavailable_reason"] = "Public stats are unavailable after FogHTTP client close"
        self.mark("after_client_close")

    def record_error(self, stage: str, exc: BaseException) -> None:
        self.errors.append({"stage": stage, "type": type(exc).__name__, "message": str(exc)})
        self.save()

    def url(self) -> str:
        return self.base_url + "/stream?" + urlencode({"control": "normal", "id": uuid.uuid4().hex})

    def batch(self, number: int, rounds: int, samples: list[LifecycleStreamSample], duration: float) -> JsonObject:
        requests = rounds * self.case.concurrency
        return {
            "batch": number,
            "rounds": rounds,
            "requests": requests,
            "ok_streams": len(samples),
            "duration_s": duration,
            "streams_per_second": requests / duration if duration > 0 else None,
            "bytes_read_total": sum(sample.bytes_read for sample in samples),
            "chunks_read_total": sum(sample.chunks_read for sample in samples),
            "expected_aborts": 0,
            "expected_abort_reason": "Measured first chunks may follow transport EOF; only held-tail proves abort",
            "errors": [],
            "samples": [sample.payload() for sample in samples],
        }


def _client_config(case: LifecycleCase, config: LifecycleConfig) -> StreamingClientConfig:
    return StreamingClientConfig(
        concurrency=case.concurrency,
        request_limit=case.concurrency,
        pool_timeout_s=config.settle_timeout_s,
        read_timeout_s=config.settle_timeout_s,
        total_timeout_s=2 * config.settle_timeout_s,
    )


def _client_configuration(case: LifecycleCase, config: LifecycleConfig) -> JsonObject:
    configured = _client_config(case, config)
    return {
        "concurrency": configured.concurrency,
        "request_limit": configured.request_limit,
        "connect_timeout_s": 2.0,
        "write_timeout_s": 10.0,
        "pool_timeout_s": configured.pool_timeout_s,
        "read_timeout_s": configured.read_timeout_s,
        "total_timeout_s": configured.total_timeout_s if case.client == "foghttp" else None,
        "total_timeout_unavailable_reason": (
            None if case.client == "foghttp" else "HTTPX factory configures per-operation timeouts, not a total timeout"
        ),
        "trust_env": False,
        "trust_env_policy": (
            "FogHTTP public default is False" if case.client == "foghttp" else "HTTPX factory explicitly sets False"
        ),
        "http_version_policy": "Local HTTP/1.1 server; actual response version is checked for every stream",
    }


def _sync_batch(
    worker: _Worker,
    adapter: SyncStreamingAdapter,
    executor: ThreadPoolExecutor,
    number: int,
    rounds: int,
) -> JsonObject:
    client = sync_client(adapter)
    digest = expected_body_digest(worker.config.body_bytes)
    samples: list[LifecycleStreamSample] = []
    duration = 0.0
    for _ in range(rounds):
        urls = [worker.url() for _ in range(worker.case.concurrency)]
        started = time.perf_counter()
        futures = [
            executor.submit(
                consume_sync_stream,
                client,
                url,
                body_bytes=worker.config.body_bytes,
                first_chunk=worker.case.case == "first-chunk-close-1m",
                expected_digest=digest,
            )
            for url in urls
        ]
        wait(futures)
        duration += time.perf_counter() - started
        for future in futures:
            error = future.exception()
            if error is not None:
                worker.record_error(f"batch-{number}", error)
            else:
                samples.append(future.result())
    batch = worker.batch(number, rounds, samples, duration)
    batch["errors"] = [error for error in worker.errors if error["stage"] == f"batch-{number}"]
    return batch


async def _async_batch(worker: _Worker, adapter: AsyncStreamingAdapter, number: int, rounds: int) -> JsonObject:
    if worker.config.attribution is not None:
        # Attribution types end at the mixed lifecycle report boundary; the dict is unchanged.
        return cast("JsonObject", await _attribution_batch(worker, adapter, number, rounds))
    client = async_client(adapter)
    digest = expected_body_digest(worker.config.body_bytes)
    samples: list[LifecycleStreamSample] = []
    duration = 0.0
    for _ in range(rounds):
        urls = [worker.url() for _ in range(worker.case.concurrency)]
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                consume_async_stream(
                    client,
                    url,
                    body_bytes=worker.config.body_bytes,
                    first_chunk=worker.case.case == "first-chunk-close-1m",
                    expected_digest=digest,
                )
                for url in urls
            ),
            return_exceptions=True,
        )
        duration += time.perf_counter() - started
        for result in results:
            if isinstance(result, BaseException):
                worker.record_error(f"batch-{number}", result)
            else:
                samples.append(result)
    batch = worker.batch(number, rounds, samples, duration)
    batch["errors"] = [error for error in worker.errors if error["stage"] == f"batch-{number}"]
    return batch


async def _attribution_batch(
    worker: _Worker,
    adapter: AsyncStreamingAdapter,
    number: int,
    rounds: int,
) -> AttributionBatch:
    config = worker.config.attribution
    if config is None:
        msg = "Bytes batch requires attribution configuration"
        raise ValueError(msg)
    before = await asyncio.to_thread(control_json, worker.base_url, "/summary")
    server_pid = before.get("pid")
    if type(server_pid) is not int or server_pid <= 0 or server_pid == os.getpid():
        msg = "Bytes measurement server PID must identify a separate process"
        raise ValueError(msg)
    batch = await measure_async_batch(
        async_client(adapter),
        worker.base_url,
        body_bytes=worker.config.body_bytes,
        concurrency=worker.case.concurrency,
        rounds=rounds,
        config=config,
        server_pid=server_pid,
        batch=number,
        python_profile_path=(worker.output.parent / "profiles" / f"python-batch-{number:03d}.pstats")
        if config.profiler == "cprofile" and number > 0
        else None,
    )
    batch["server_before"] = before
    errors = batch["errors"]
    if errors:
        worker.record_error(f"batch-{number}", ValueError(f"{len(errors)} async bytes measurement errors"))
    return batch


async def _attribution_server_health(worker: _Worker, batch: JsonObject) -> None:
    if worker.config.attribution is None:
        return
    after = await asyncio.to_thread(control_json, worker.base_url, "/summary")
    before = cast("JsonObject", batch["server_before"])
    expected = cast("int", batch["requests"])
    errors = []
    if (
        before.get("pid") != after.get("pid")
        or after.get("body_bytes") != worker.config.body_bytes
        or after.get("server_write_bytes") != worker.config.server_write_bytes
        or after.get("server_delay_s") != worker.config.attribution.server_delay_s
        or after.get("content_encoding") is not None
        or after.get("active_requests") != 0
        or cast("JsonObject", after.get("body_observations", {})).get("enabled")
        is not worker.config.attribution.server_observations
    ):
        errors.append("Server identity, configuration or quiescence differs from the declared workload")
    for counter, delta in (
        ("normal_eof_total", expected),
        ("normal_disconnected_total", 0),
        ("unexpected_errors_total", 0),
    ):
        initial, final = before.get(counter), after.get(counter)
        if type(initial) is not int or type(final) is not int or final - initial != delta:
            errors.append(f"Server {counter} did not change by the expected {delta}")
    if worker.config.attribution.server_observations:
        evidence, failures = _server_delivery_evidence(
            before,
            after,
            expected=expected,
            writes=expected * math.ceil(worker.config.body_bytes / worker.config.server_write_bytes),
        )
        batch["server_delivery"] = evidence
        errors.extend(failures)
    batch["server_health"] = {
        "status": "failed" if errors else "ok",
        "before": before,
        "after": after,
        "errors": errors,
    }
    if errors:
        worker.record_error("server-health", ValueError("; ".join(errors)))


def _server_delivery_evidence(
    before: JsonObject,
    after: JsonObject,
    *,
    expected: int,
    writes: int,
) -> tuple[JsonObject, list[str]]:
    initial, final = before.get("body_delivery_totals"), after.get("body_delivery_totals")
    if not isinstance(initial, dict) or not isinstance(final, dict):
        return {}, ["Declared server body observations are missing"]
    errors = []
    deltas: JsonObject = {}
    for counter in (
        "streams",
        "body_loop_elapsed_ns",
        "write_elapsed_ns",
        "drain_elapsed_ns",
        "write_calls",
        "drain_calls",
        "drains_completed",
    ):
        start, end = initial.get(counter), final.get(counter)
        if type(start) is not int or type(end) is not int or end < start:
            errors.append(f"Server body observation {counter} is missing or decreased")
        else:
            deltas[counter] = end - start
    if deltas.get("streams") != expected or any(
        deltas.get(key) != writes for key in ("write_calls", "drain_calls", "drains_completed")
    ):
        errors.append("Server body write/drain totals do not cover every declared completed response")
    return {
        "deltas": deltas,
        "cumulative_max_transport_buffer_bytes": final.get("max_transport_buffer_bytes"),
        "scope": (
            "Completed normal EOF bodies; concurrent wall sums overlap; drain wait is not network acknowledgement; "
            "maximum is cumulative including warmup"
        ),
    }, errors


_Adapter = TypeVar("_Adapter", AsyncStreamingAdapter, SyncStreamingAdapter)


def _client_spec(worker: _Worker) -> StreamingClientSpec:
    clients, skipped = available_streaming_clients([worker.case.client], [worker.case.mode])
    if len(clients) != 1:
        msg = f"Lifecycle client is unavailable: {skipped}"
        raise RuntimeError(msg)
    return clients[0]


def _make_adapter(worker: _Worker, factory: Callable[[StreamingClientConfig], _Adapter]) -> _Adapter:
    started = time.perf_counter_ns()
    adapter = factory(_client_config(worker.case, worker.config))
    worker.report["client_construction_ms"] = (time.perf_counter_ns() - started) / 1_000_000
    return adapter


def _run_sync(worker: _Worker) -> None:
    spec = _client_spec(worker)
    if spec.mode != SYNC_MODE:
        msg = "Lifecycle sync worker received a different client mode"
        raise RuntimeError(msg)
    adapter = _make_adapter(worker, spec.factory)
    batches: list[JsonObject] = []
    worker.report["batches"] = batches
    try:
        with ThreadPoolExecutor(max_workers=worker.case.concurrency) as executor:
            worker.observe("before_load", adapter)
            worker.report["warmup"] = _sync_batch(worker, adapter, executor, 0, worker.config.warmup_rounds)
            wait_quiet(adapter, worker.base_url, worker.config.settle_timeout_s)
            worker.observe("post_warmup", adapter)
            for number in range(1, worker.config.batches + 1):
                worker.mark(f"batch_{number}_start")
                batches.append(_sync_batch(worker, adapter, executor, number, worker.config.rounds_per_batch))
                wait_quiet(adapter, worker.base_url, worker.config.settle_timeout_s)
                worker.observe(f"post_batch_{number}", adapter)
            worker.mark("controls_start")
            worker.report["controls"] = run_sync_controls(
                adapter,
                executor,
                worker.base_url,
                worker.config,
                worker.case.concurrency,
            )
            worker.observe("before_client_close", adapter)
    finally:
        started = time.perf_counter_ns()
        adapter.close()
        worker.report["client_close_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        worker.observe_closed()


async def _run_async(worker: _Worker) -> None:
    spec = _client_spec(worker)
    if spec.mode != ASYNC_MODE:
        msg = "Lifecycle async worker received a different client mode"
        raise RuntimeError(msg)
    adapter = _make_adapter(worker, spec.factory)
    batches: list[JsonObject] = []
    worker.report["batches"] = batches
    close_allowed = True
    try:
        worker.observe("before_load", adapter)
        worker.report["warmup"] = await _async_batch(worker, adapter, 0, worker.config.warmup_rounds)
        await asyncio.to_thread(wait_quiet, adapter, worker.base_url, worker.config.settle_timeout_s)
        await _attribution_server_health(worker, cast("JsonObject", worker.report["warmup"]))
        worker.observe("post_warmup", adapter)
        for number in range(1, worker.config.batches + 1):
            worker.mark(f"batch_{number}_start")
            batches.append(await _async_batch(worker, adapter, number, worker.config.rounds_per_batch))
            await asyncio.to_thread(wait_quiet, adapter, worker.base_url, worker.config.settle_timeout_s)
            await _attribution_server_health(worker, batches[-1])
            worker.observe(f"post_batch_{number}", adapter)
        worker.mark("controls_start")
        worker.report["controls"] = await run_async_controls(
            adapter,
            worker.base_url,
            worker.config,
            worker.case.concurrency,
        )
        worker.observe("before_client_close", adapter)
    except UnsettledWorkers as exc:
        close_allowed = False
        worker.report["force_reap_reason"] = str(exc)
        worker.record_error("cancellation-settlement", exc)
        raise
    finally:
        if close_allowed:
            started = time.perf_counter_ns()
            await adapter.close()
            worker.report["client_close_ms"] = (time.perf_counter_ns() - started) / 1_000_000
            worker.observe_closed()


def run_lifecycle_worker(
    case: LifecycleCase,
    config: LifecycleConfig,
    *,
    server_url: str,
    control_dir: Path,
    output: Path,
) -> JsonObject:
    worker = _Worker(case, config, server_url, control_dir, output)
    worker.report.update(
        {
            "status": "failed",
            "case": asdict(case),
            "config": asdict(config),
            "worker_pid": os.getpid(),
            "measurement_scope": "isolated-client; server sampled separately by parent",
            "timing_scope": "stream enter, public bytes consumption and context exit; includes incremental SHA-256",
            "throughput_scope": (
                "sum of round wall times, including scheduling, integrity validation and scalar observations"
            ),
            "scalar_sample_cap": (
                config.attribution.max_window_streams
                if config.attribution is not None and config.attribution.minimum_duration_s
                else 1000
            ),
            "scalar_sample_cap_scope": (
                "Measured duration window only; hard stream limit; warmup and controls separately bounded"
                if config.attribution is not None and config.attribution.minimum_duration_s
                else "Measured fixed-round batches only; warmup and controls separately bounded by configuration"
            ),
            "gc_policy": "automatic GC unchanged; optional explicit collection after client close",
            "gc_configuration": {
                "enabled": gc.isenabled(),
                "threshold": list(gc.get_threshold()),
                "explicit_collection_after_client_close": config.post_gc,
                "automatic_policy_changed": False,
            },
            "proxy_environment_presence": {
                name: name in os.environ
                for name in (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "ALL_PROXY",
                    "NO_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "all_proxy",
                    "no_proxy",
                )
            },
        },
    )
    try:
        validate_lifecycle_case(case, config)
        validate_lifecycle_config(config)
        if config.attribution is not None:
            _attribution_environment(worker)
        worker.report["client_configuration"] = _client_configuration(case, config)
        provenance = research_provenance_from_env()
        metadata: JsonObject = {
            "suite": "response-streaming",
            "profile": "async-bytes" if config.attribution is not None else "lifecycle",
            "package_sources": package_sources(["foghttp"] if provenance is not None else [case.client]),
            "measured_package_sources": package_sources([case.client]),
        }
        if provenance is not None:
            metadata["research_provenance"] = provenance
        worker.report["metadata"] = metadata
        if case.mode == "async":
            asyncio.run(_run_async(worker))
        else:
            _run_sync(worker)
        if config.post_gc:
            started = time.perf_counter_ns()
            gc.collect()
            worker.report["post_gc_duration_ms"] = (time.perf_counter_ns() - started) / 1_000_000
            worker.mark("post_gc")
        _verify_unchanged_provenance(provenance)
        worker.report["status"] = "failed" if worker.errors else "ok"
    except Exception as exc:  # noqa: BLE001 - child boundary preserves every unexpected failure in partial output.
        worker.record_error("worker", exc)
    finally:
        worker.save()
    return worker.report


def _attribution_environment(worker: _Worker) -> None:
    presence = cast("dict[str, bool]", worker.report["proxy_environment_presence"])
    if any(presence.values()):
        msg = "Async bytes measurements require an environment without proxy variables; values are not recorded"
        raise ValueError(msg)
    attribution = worker.config.attribution
    if attribution is None:
        msg = "Attribution environment check requires explicit configuration"
        raise ValueError(msg)
    profiler_present = active_python_instrumentation()
    if profiler_present and attribution.instrumentation != "diagnostic":
        msg = "Active Python profiling/tracing requires diagnostic instrumentation"
        raise ValueError(msg)
    worker.report.update(
        {
            "profile": "async-bytes",
            "timing_scope": "async-bytes-load-v1; incremental hash and bounded scalar bookkeeping included",
            "throughput_scope": (
                "verified EOF bytes / load wall; verdict, digest finalization, CPU probes and disk I/O outside"
            ),
            "python_profiler_or_trace_active": profiler_present,
        },
    )


def _verify_unchanged_provenance(initial: JsonObject | None) -> None:
    if research_provenance_from_env() != initial:
        msg = "Research provenance changed during lifecycle work"
        raise ValueError(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Owned isolated streaming lifecycle client worker")
    parser.add_argument("--case-file", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.case_file.read_text())
    result = run_lifecycle_worker(
        LifecycleCase(**value["case"]),
        lifecycle_config_from_payload(value["config"]),
        server_url=args.server_url,
        control_dir=args.control_dir,
        output=args.output,
    )
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
