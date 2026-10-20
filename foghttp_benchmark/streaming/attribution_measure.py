__all__ = ("measure_async_batch", "replay_harness_overhead")

import asyncio
from collections.abc import Iterator
import hashlib
import importlib
import os
from pathlib import Path
import time
from typing import cast
from urllib.parse import urlencode
import uuid

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.attribution_consume import (
    ChunkObservations,
    ObservationBudget,
    PendingStream,
    consume_attribution_stream,
)
from foghttp_benchmark.streaming.attribution_models import (
    MAX_REPLAY_SEGMENTS,
    AttributionConfig,
    validate_attribution_config,
)
from foghttp_benchmark.streaming.attribution_payloads import (
    AttributionBatch,
    CpuDelta,
    CpuRole,
    CpuSnapshot,
    CpuSnapshotInProgress,
)
from foghttp_benchmark.streaming.bytes_payloads import streaming_bytes_sha256
from foghttp_benchmark.streaming.protocols import AsyncStreamClient
from foghttp_benchmark.streaming.python_profile import PythonLoadProfile


MAX_BODY_BYTES = 1_048_576
MAX_ROUNDS = 20
CPU_ROLES: tuple[CpuRole, ...] = ("client", "server")


def _cpu_snapshot(pid: int) -> CpuSnapshot:
    started = time.perf_counter_ns()
    result: CpuSnapshotInProgress = {
        "pid": pid,
        "probe_started_ns": started,
        "user_s": None,
        "system_s": None,
        "reason": None,
    }
    try:
        process = importlib.import_module("psutil").Process(pid)
        counters = process.cpu_times()
        result.update({"user_s": float(counters.user), "system_s": float(counters.system)})
    except Exception as error:  # noqa: BLE001 - missing process counters remain explicit unavailable evidence.
        result["reason"] = f"{type(error).__name__}: {error}"
    result["probe_finished_ns"] = time.perf_counter_ns()
    # The completed probe has the required end timestamp; no runtime copy or validation.
    return cast("CpuSnapshot", result)


def _cpu_delta(
    before: CpuSnapshot,
    after: CpuSnapshot,
    *,
    started_ns: int,
    finished_ns: int,
    verified_bytes: int,
) -> CpuDelta:
    user = system = None
    reason = before["reason"] or after["reason"]
    if reason is None:
        # A successful probe sets both counters. Keep this invariant without new probe checks.
        start_user, end_user = cast("float", before["user_s"]), cast("float", after["user_s"])
        start_system, end_system = cast("float", before["system_s"]), cast("float", after["system_s"])
        if end_user < start_user or end_system < start_system:
            reason = "Process CPU counter decreased"
        else:
            user, system = end_user - start_user, end_system - start_system
    total = user + system if user is not None and system is not None else None
    duration = (finished_ns - started_ns) / 1_000_000_000
    return {
        "pid": before["pid"],
        "user_s": user,
        "system_s": system,
        "total_s": total,
        "cpu_seconds_per_verified_byte": total / verified_bytes if total is not None and verified_bytes else None,
        "cpu_seconds_per_wall_second": total / duration if total is not None and duration > 0 else None,
        "unavailable_reason": reason,
        "normalization_unavailable_reason": None if verified_bytes else "No verified-success bytes",
        "before": before,
        "after": after,
        "load_boundary_overhang_ns": (
            started_ns - before["probe_started_ns"] + after["probe_finished_ns"] - finished_ns
        ),
        "scope": "Separate process user/system counters bracketing load, including the reported boundary probe span",
        "resolution_s": None,
        "resolution_unavailable_reason": "psutil/OS process counter resolution is not exposed by this measurement",
        "cpu_wall_interpretation": "Aggregate process CPU seconds / wall seconds; multiple cores may exceed one",
    }


def _observed_histogram(observations: list[ChunkObservations], bins_cap: int) -> tuple[dict[int, int], bool]:
    histogram: dict[int, int] = {}
    complete = all(item.histogram_complete for item in observations)
    for item in observations:
        for size, count in item.histogram.items():
            if size in histogram or len(histogram) < bins_cap:
                histogram[size] = histogram.get(size, 0) + count
            else:
                complete = False
    return histogram, complete


def _replay_segments(histogram: dict[int, int], config: AttributionConfig) -> Iterator[dict[int, int]]:
    segment: dict[int, int] = {}
    byte_count = chunk_count = 0
    for size, count in sorted(histogram.items()):
        remaining = count
        while remaining:
            capacity = min((config.replay_max_bytes - byte_count) // size, config.replay_max_chunks - chunk_count)
            if not capacity:
                yield segment
                segment, byte_count, chunk_count = {}, 0, 0
                continue
            taken = min(remaining, capacity)
            segment[size] = segment.get(size, 0) + taken
            byte_count += size * taken
            chunk_count += taken
            remaining -= taken
    if segment:
        yield segment


def _replay_histogram(histogram: dict[int, int], config: AttributionConfig) -> JsonObject:
    source = memoryview(bytes(max(histogram)))
    result: JsonObject = {
        "replay_bytes": sum(size * count for size, count in histogram.items()),
        "replay_chunks": sum(histogram.values()),
    }
    for variant in ("scalar_only", "sha256_only", "combined"):
        observer = ChunkObservations(config)
        digest = hashlib.sha256()
        started = time.perf_counter_ns()
        for size, count in sorted(histogram.items()):
            chunk = source[:size]
            for _ in range(count):
                if variant != "sha256_only":
                    observer.observe(chunk, time.perf_counter_ns(), started)
                if variant != "scalar_only":
                    digest.update(chunk)
        finished = time.perf_counter_ns()
        result[variant + "_s"] = (finished - started) / 1_000_000_000
        digest.hexdigest()
    return result


def _replay_failure_reason(
    histogram: dict[int, int],
    *,
    complete: bool,
    observed_bytes: int,
    observed_chunks: int,
    config: AttributionConfig,
    window: bool,
) -> str | None:
    if not complete:
        return "Observed chunk size histogram exceeded its bound; exact distribution unavailable"
    if not observed_chunks:
        return "No delivered chunks to replay"
    if not window and (observed_bytes > config.replay_max_bytes or observed_chunks > config.replay_max_chunks):
        return "Exact distribution exceeds explicit overhead replay byte/chunk limit"
    if (
        not histogram
        or sum(histogram.values()) != observed_chunks
        or sum(size * count for size, count in histogram.items()) != observed_bytes
    ):
        return "Histogram does not exactly cover every observed byte and chunk"
    if max(histogram) > config.replay_max_bytes:
        return "An observed chunk exceeds the explicit replay byte limit"
    return None


def replay_harness_overhead(
    observations: list[ChunkObservations],
    config: AttributionConfig,
    *,
    window_budget: ObservationBudget | None = None,
) -> JsonObject:
    if window_budget is not None and window_budget.global_histogram is not None:
        histogram, complete = window_budget.global_histogram, window_budget.global_histogram_complete
    else:
        histogram, complete = _observed_histogram(observations, config.histogram_bins_cap)
    observed_bytes = sum(item.bytes_read for item in observations)
    observed_chunks = sum(item.chunks_read for item in observations)
    result: JsonObject = {
        "status": "unavailable",
        "distribution_complete": complete,
        "observed_bytes": observed_bytes,
        "observed_chunks": observed_chunks,
        "replay_bytes": 0,
        "replay_chunks": 0,
        "scalar_only_s": None,
        "sha256_only_s": None,
        "combined_s": None,
        "reason": None,
        "limits": {
            "bytes": config.replay_max_bytes,
            "chunks": config.replay_max_chunks,
            "bins": config.histogram_bins_cap,
        },
        "scope": (
            "Offline synthetic memoryview replay of exact observed size histogram; sorted sizes, original order omitted"
        ),
        "limitation": (
            "Harness cost estimate only; no transport/copy/wakeup attribution or baseline subtraction; "
            "excludes asyncio scheduling, slow-consumer sleeps and diagnostic await trace; "
            "one synthetic observer, original per-stream reset/sample-cap behavior differs; one replay per variant"
        ),
    }
    if window_budget is not None:
        cast("JsonObject", result["limits"])["segments"] = MAX_REPLAY_SEGMENTS
        result["limitation"] = (
            "Harness cost estimate only; no transport/copy/wakeup attribution or baseline subtraction; "
            "excludes asyncio scheduling, slow-consumer sleeps and diagnostic await trace; "
            "one synthetic observer/digest reset per segment, original per-stream and shared-budget behavior differs; "
            "one replay per variant per segment"
        )
    failure = _replay_failure_reason(
        histogram,
        complete=complete,
        observed_bytes=observed_bytes,
        observed_chunks=observed_chunks,
        config=config,
        window=window_budget is not None,
    )
    if failure is not None:
        result["reason"] = failure
        return result
    if window_budget is None:
        result.update(_replay_histogram(histogram, config))
    else:
        segment_histograms: list[dict[int, int]] = []
        for segment_histogram in _replay_segments(histogram, config):
            if len(segment_histograms) >= MAX_REPLAY_SEGMENTS:
                result["reason"] = "Exact distribution exceeds the bounded 64-segment replay limit"
                return result
            segment_histograms.append(segment_histogram)
        segments = [
            {
                **_replay_histogram(segment, config),
                "histogram": [{"size_bytes": size, "count": count} for size, count in sorted(segment.items())],
            }
            for segment in segment_histograms
        ]
        result.update(
            {
                "segments": segments,
                "replay_bytes": sum(cast("int", segment["replay_bytes"]) for segment in segments),
                "replay_chunks": sum(cast("int", segment["replay_chunks"]) for segment in segments),
                **{
                    key: sum(cast("float", segment[key]) for segment in segments)
                    for key in ("scalar_only_s", "sha256_only_s", "combined_s")
                },
                "scope": (
                    "Offline synthetic memoryview replay of the exact whole-window histogram; "
                    "sorted sizes, original order omitted; each segment stays within the unchanged replay limits"
                ),
            },
        )
    result["status"] = "ok"
    return result


def _python_profile(config: AttributionConfig, *, batch: int, path: Path | None) -> PythonLoadProfile | None:
    if config.profiler != "cprofile" or batch == 0:
        return None
    if path is None:
        msg = "Measured cProfile load requires an explicit worker-owned profile path"
        raise ValueError(msg)
    return PythonLoadProfile(path)


async def _consume_load(
    client: AsyncStreamClient,
    urls: list[str],
    *,
    body_bytes: int,
    concurrency: int,
    rounds: int,
    config: AttributionConfig,
    budget: ObservationBudget,
    window: bool,
    profile: PythonLoadProfile | None,
) -> tuple[list[PendingStream], int, int]:
    pending: list[PendingStream] = []
    if profile is not None:
        profile.start()
    started = time.perf_counter_ns()
    try:
        for offset in range(0, len(urls), concurrency):
            pending.extend(
                await asyncio.gather(
                    *(
                        consume_attribution_stream(
                            client,
                            urls[index],
                            body_bytes=body_bytes,
                            stream=index + 1,
                            config=config,
                            budget=budget,
                        )
                        for index in range(offset, offset + concurrency)
                    ),
                ),
            )
            if (
                window
                and len(pending) >= rounds * concurrency
                and time.perf_counter_ns() - started >= config.minimum_duration_s * 1_000_000_000
            ):
                break
    finally:
        finished = time.perf_counter_ns()
        if profile is not None:
            profile.stop()
    return pending, started, finished


async def measure_async_batch(
    client: AsyncStreamClient,
    base_url: str,
    *,
    body_bytes: int,
    concurrency: int,
    rounds: int,
    config: AttributionConfig,
    server_pid: int,
    batch: int,
    python_profile_path: Path | None = None,
) -> AttributionBatch:
    client_module = type(client).__module__.split(".", 1)[0]
    validate_attribution_config(config, client=client_module)
    if type(body_bytes) is not int or not 0 < body_bytes <= MAX_BODY_BYTES:
        msg = "Attribution payload must be a positive integer within 1 MiB"
        raise ValueError(msg)
    if (
        type(concurrency) is not int
        or concurrency not in {1, 10}
        or type(rounds) is not int
        or not 0 <= rounds <= MAX_ROUNDS
    ):
        msg = "Attribution batch requires concurrency 1/10 and zero to twenty bounded rounds"
        raise ValueError(msg)
    window = config.minimum_duration_s > 0 and batch > 0
    if window and (rounds <= 0 or rounds * concurrency > config.max_window_streams):
        msg = "Timed window minimum rounds must fit the explicit stream bound"
        raise ValueError(msg)
    maximum_requests = config.max_window_streams // concurrency * concurrency if window else rounds * concurrency
    urls = [
        base_url + "/stream?" + urlencode({"control": "normal", "id": uuid.uuid4().hex})
        for _ in range(maximum_requests)
    ]
    expected = streaming_bytes_sha256(body_bytes)
    profile = _python_profile(config, batch=batch, path=python_profile_path)
    before: dict[CpuRole, CpuSnapshot] = {"client": _cpu_snapshot(os.getpid()), "server": _cpu_snapshot(server_pid)}
    budget = (
        ObservationBudget(histogram_bins_cap=config.histogram_bins_cap, global_histogram={})
        if window
        else ObservationBudget()
    )
    pending, started, finished = await _consume_load(
        client,
        urls,
        body_bytes=body_bytes,
        concurrency=concurrency,
        rounds=rounds,
        config=config,
        budget=budget,
        window=window,
        profile=profile,
    )
    requests = len(pending)
    actual_rounds = requests // concurrency
    after: dict[CpuRole, CpuSnapshot] = {"client": _cpu_snapshot(os.getpid()), "server": _cpu_snapshot(server_pid)}
    finalize_started = time.perf_counter_ns()
    samples = [item.finalize(body_bytes=body_bytes, expected_digest=expected) for item in pending]
    finalize_duration = time.perf_counter_ns() - finalize_started
    verified = sum(sample["verified_success_bytes"] for sample in samples)
    observed = sum(item.observations.bytes_read for item in pending)
    ok = sum(sample["status"] == "ok" for sample in samples)
    duration = (finished - started) / 1_000_000_000
    observation_budget = budget.payload()
    observed_chunks = sum(item.observations.chunks_read for item in pending)
    recorded_deliveries = sum(len(item.observations.delivery_samples) for item in pending)
    recorded_traces = sum(len(item.observations.trace) for item in pending)
    observation_budget.update(
        {
            "total_deliveries": observed_chunks,
            "recorded_delivery_samples": recorded_deliveries,
            "dropped_delivery_samples": observed_chunks - recorded_deliveries,
            "recorded_trace_samples": recorded_traces,
            "dropped_trace_samples": observed_chunks - recorded_traces if config.instrumentation == "diagnostic" else 0,
            "histogram_complete": budget.global_histogram_complete
            if window
            else all(item.observations.histogram_complete for item in pending),
        },
    )
    result: AttributionBatch = {
        "batch": batch,
        "rounds": actual_rounds,
        "requests": requests,
        "ok_streams": ok,
        "duration_s": duration,
        "streams_per_second": requests / duration if duration else None,
        "ok_streams_per_second": ok / duration if duration else None,
        "verified_success_bytes": verified,
        "total_observed_bytes": observed,
        "failed_observed_bytes": observed - verified,
        "bytes_read_total": verified,
        "chunks_read_total": observed_chunks,
        "verified_bytes_per_second": verified / duration if duration else None,
        "mb_per_second": verified / (1024 * 1024) / duration if duration else None,
        "expected_aborts": 0,
        "errors": [{"stream": sample["stream"], **sample["error"]} for sample in samples if sample["error"]],
        "samples": samples,
        "observation_budget": observation_budget,
        "cpu": {
            role: _cpu_delta(
                before[role],
                after[role],
                started_ns=started,
                finished_ns=finished,
                verified_bytes=verified,
            )
            for role in CPU_ROLES
        },
        "timing": {
            "load_started_ns": started,
            "load_finished_ns": finished,
            "clock": "time.perf_counter_ns; monotonic; nanoseconds",
            "clock_resolution_s": time.get_clock_info("perf_counter").resolution,
            "scope": (
                "Async scheduling, bytes iteration, incremental SHA-256, scalar observations, "
                "consumer delays and context exit; stops before CPU end probes, digest finalization/comparison, "
                "replay, sampler teardown, client close and reports"
            ),
            "digest_finalize_duration_ns": finalize_duration,
            "verified_only_after_finalization": True,
        },
        "overhead": replay_harness_overhead([item.observations for item in pending], config, window_budget=budget)
        if window
        else replay_harness_overhead([item.observations for item in pending], config),
        "attribution_limits": {
            "native_copy_count": None,
            "event_loop_wakeups": None,
            "future_completions": None,
            "unavailable_reason": (
                "Public bytes delivery/await observations cannot isolate native copies, "
                "loop wakeups or Future completion cost"
            ),
        },
    }
    if profile is not None:
        result["python_profile"] = profile.write(load_started_ns=started, load_finished_ns=finished)
    if window:
        target_reached = duration >= config.minimum_duration_s
        result["window"] = {
            "minimum_duration_s": config.minimum_duration_s,
            "minimum_rounds": rounds,
            "max_streams": config.max_window_streams,
            "stop_reason": "duration-reached" if target_reached else "stream-limit",
            "target_reached": target_reached,
            "global_histogram": {
                "histogram": [
                    {"size_bytes": size, "count": count}
                    for size, count in sorted((budget.global_histogram or {}).items())
                ],
                "complete": budget.global_histogram_complete,
                "observed_count": observed_chunks,
                "observed_bytes": observed,
                "bins_cap": config.histogram_bins_cap,
                "scope": "batch-global",
            },
        }
    return result
