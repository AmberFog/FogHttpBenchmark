__all__ = ("aggregate_attribution_results", "revalidate_attribution_rows", "write_attribution_reports")

from dataclasses import asdict
from http import HTTPStatus
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

from foghttp_benchmark.attribution_evidence import (
    ATTRIBUTION_POLICY_VERSION,
    ATTRIBUTION_SCHEMA_VERSION,
    condition_fingerprint,
    inspect_raw_evidence,
    write_raw_sidecar,
)
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.provenance import capture_harness, package_sources
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.streaming.attribution_window import window_distribution_matches, window_workload_matches
from foghttp_benchmark.streaming.lifecycle_consume import expected_body_digest
from foghttp_benchmark.streaming.lifecycle_models import BASELINE_CONFIG, LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_reports import (
    MEASUREMENT_SCOPE,
    aggregate_lifecycle_results,
    child_diagnostic,
    cv_optional,
    median_optional,
    number,
    object_list,
    object_value,
    quantile,
)
from foghttp_benchmark.validity.reports import metadata_with_validity


TIMING_SCOPE = "load-only-incremental-sha256-v1"
GC_THRESHOLD_COUNT = 3


def measurement_conditions(config: LifecycleConfig, environment: JsonObject) -> JsonObject:
    return {
        "policy_version": ATTRIBUTION_POLICY_VERSION,
        "configuration": asdict(config),
        "payload": "bytes(range(256)) repeated; sha256; uncompressed",
        "framing": "HTTP/1.1 Content-Length; no Transfer-Encoding or Content-Encoding",
        "server_placement": "fresh separate owned loopback process",
        "timing_scope": TIMING_SCOPE,
        "measurement_scope": MEASUREMENT_SCOPE,
        "sampling": "bounded-first-public-chunks; perf_counter_ns monotonic nanoseconds",
        "environment": environment,
    }


def aggregate_attribution_results(results: list[JsonObject], conditions: JsonObject) -> list[JsonObject]:
    rows = aggregate_lifecycle_results(results)
    for row in rows:
        selected = [result for result in results if same_cell(object_value(result.get("case")), row)]
        children = [object_value(result.get("client_report")) for result in selected]
        batches = [batch for child in children for batch in object_list(child.get("batches"))]
        samples = [sample for batch in batches for sample in object_list(batch.get("samples"))]
        repeat_rates = [repeat_verified_rate(child) for child in children]
        actual_rates = [value for value in repeat_rates if value is not None]
        observed = sum(integer(batch.get("total_observed_bytes")) for batch in batches)
        verified = sum(integer(batch.get("verified_success_bytes")) for batch in batches)
        own_conditions = {
            **conditions,
            "read_policy": "public-iterator-requested-size"
            if row["client"] != "foghttp"
            and object_value(object_value(conditions.get("configuration")).get("attribution")).get(
                "requested_client_read_bytes",
            )
            is not None
            else "native-public-iterator",
            "requested_client_read_bytes": None
            if row["client"] == "foghttp"
            else object_value(object_value(conditions.get("configuration")).get("attribution")).get(
                "requested_client_read_bytes",
            ),
        }
        row.update(
            profile="async-bytes",
            schema_version=ATTRIBUTION_SCHEMA_VERSION,
            policy_version=ATTRIBUTION_POLICY_VERSION,
            conditions=own_conditions,
            condition_fingerprint=condition_fingerprint(own_conditions),
            primary_metric="verified_bytes_s_median",
            timing_scope=TIMING_SCOPE,
            throughput_scope="verified-eof-v2",
            verified_bytes_total=verified,
            total_observed_bytes=observed,
            failed_observed_bytes=sum(integer(batch.get("failed_observed_bytes")) for batch in batches),
            verified_bytes_s_median=median_optional(actual_rates),
            verified_bytes_s_cv_percent=cv_optional(actual_rates),
            variation_sample_count=len(actual_rates),
            integrity_failures_total=sum(sample.get("status") != "ok" for sample in samples),
            complete_streams_total=sum(
                sample.get("status") == "ok" and sample.get("eof") is True for sample in samples
            ),
            expected_streams_total=sum(integer(batch.get("requests")) for batch in batches)
            if object_value(object_value(row.get("configuration")).get("attribution")).get("minimum_duration_s")
            else (
                integer(object_value(row.get("configuration")).get("batches"))
                * integer(object_value(row.get("configuration")).get("rounds_per_batch"))
                * integer(row.get("concurrency"))
                * len(selected)
            ),
            stream_samples_total=len(samples),
            delivered_chunks_total=sum(integer(sample.get("chunks_read")) for sample in samples),
            chunk_bytes_min=extreme_chunk(samples, "min_bytes", minimum=True),
            chunk_bytes_max=extreme_chunk(samples, "max_bytes", minimum=False),
            gap_p95_ms=gap_quantile(samples, 0.95),
            gap_sample_count=sum(len(list_value(sample.get("gap_samples_ms"))) for sample in samples),
            gap_sampling_rule="first bounded public chunk observations per stream; excludes first delivery",
            cpu={role: aggregate_cpu(children, role) for role in ("client", "server")},
            overhead=aggregate_overhead(batches),
            instrumentation=object_value(object_value(conditions.get("configuration")).get("attribution")).get(
                "instrumentation",
            ),
            profiler_label=object_value(object_value(conditions.get("configuration")).get("attribution")).get(
                "profiler_label",
            ),
            stream_measurement_evidence_complete=all(
                batch_evidence_complete(batch, object_value(row.get("configuration"))) for batch in batches
            )
            and bool(batches),
            duration_window_complete=all(
                object_value(batch.get("window")).get("target_reached") is True for batch in batches
            )
            if object_value(object_value(row.get("configuration")).get("attribution")).get("minimum_duration_s")
            else True,
            load_duration_s_min=min((number(batch.get("duration_s")) or 0.0 for batch in batches), default=None),
            load_duration_s_max=max((number(batch.get("duration_s")) or 0.0 for batch in batches), default=None),
            server_health_complete=bool(batches)
            and all(object_value(batch.get("server_health")).get("status") == "ok" for batch in batches),
            cpu_pid_identity_valid=all(batch_cpu_identity(result) for result in selected),
            declared_workload_complete=all(declared_workload_matches(result) for result in selected),
            gc_configuration_matches=all(
                gc_evidence_matches(child, object_value(conditions.get("environment"))) for child in children
            ),
        )
        if object_value(object_value(conditions.get("configuration")).get("attribution")).get("profiler") == "cprofile":
            row["python_profile_thread_scope_qualified"] = all(
                object_value(batch.get("python_profile")).get("attribution_qualification") == "qualified-thread-scope"
                for batch in batches
            )
    return rows


def same_cell(case: JsonObject, row: JsonObject) -> bool:
    return all(case.get(key) == row.get(key) for key in ("mode", "client", "case", "concurrency"))


def integer(value: object) -> int:
    return value if type(value) is int else 0


def list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def repeat_verified_rate(child: JsonObject) -> float | None:
    batches = object_list(child.get("batches"))
    durations = [number(batch.get("duration_s")) for batch in batches]
    byte_values = [batch.get("verified_success_bytes") for batch in batches]
    if (
        not batches
        or any(value is None or value <= 0 for value in durations)
        or any(type(value) is not int or value < 0 for value in byte_values)
    ):
        return None
    duration = sum(value for value in durations if value is not None)
    return sum(integer(value) for value in byte_values) / duration


def extreme_chunk(samples: list[JsonObject], field: str, *, minimum: bool) -> float | None:
    values = [
        value
        for sample in samples
        if (value := number(object_value(sample.get("distribution")).get(field))) is not None
    ]
    if not values:
        return None
    return min(values) if minimum else max(values)


def batch_evidence_complete(batch: JsonObject, configuration: JsonObject) -> bool:
    window = bool(object_value(configuration.get("attribution")).get("minimum_duration_s"))
    return sample_evidence_complete(object_list(batch.get("samples")), configuration, global_distribution=window) and (
        not window or window_distribution_matches(batch, configuration)
    )


def sample_evidence_complete(
    samples: list[JsonObject],
    configuration: JsonObject,
    *,
    global_distribution: bool = False,
) -> bool:
    body = configuration.get("body_bytes")
    if type(body) is not int or not 0 < body <= BASELINE_CONFIG.body_bytes or not samples:
        return False
    expected = expected_body_digest(body)
    return all(
        sample.get("status") == "ok"
        and sample.get("eof") is True
        and sample.get("status_code") == HTTPStatus.OK
        and sample.get("content_length") == str(body)
        and sample.get("content_encoding") is None
        and sample.get("transfer_encoding") is None
        and sample.get("http_version") in {"HTTP/1.1", "1.1"}
        and sample.get("sha256") == expected
        and sample.get("bytes_read") == body
        and sample.get("verified_success_bytes") == body
        and object_value(sample.get("distribution")).get("complete") is True
        and object_value(sample.get("distribution")).get("observed_count") == sample.get("chunks_read")
        and isinstance(sample.get("delivery_samples"), list)
        and bool(sample.get("clock"))
        and (resolution := number(sample.get("clock_resolution_s"))) is not None
        and resolution > 0
        and (global_distribution or histogram_matches(sample, body))
        and latency_matches(sample)
        for sample in samples
    )


def gc_evidence_matches(child: JsonObject, environment: JsonObject) -> bool:
    actual = object_value(child.get("gc_configuration"))
    thresholds = actual.get("threshold")
    return (
        actual == environment.get("gc")
        and type(actual.get("enabled")) is bool
        and (
            isinstance(thresholds, list)
            and len(thresholds) == GC_THRESHOLD_COUNT
            and all(type(value) is int and value >= 0 for value in thresholds)
        )
        and actual.get("automatic_policy_changed") is False
    )


def latency_matches(sample: JsonObject) -> bool:
    duration = number(sample.get("duration_ms"))
    first = number(sample.get("first_item_ms"))
    close = number(sample.get("close_return_ms"))
    return (
        duration is not None
        and duration > 0
        and first is not None
        and close is not None
        and (0 <= first <= duration and 0 <= close <= duration)
    )


def histogram_matches(sample: JsonObject, body: int) -> bool:
    bins = object_list(object_value(sample.get("distribution")).get("histogram"))
    return (
        bool(bins)
        and all(
            type(item.get("size_bytes")) is int
            and integer(item.get("size_bytes")) > 0
            and type(item.get("count")) is int
            and integer(item.get("count")) > 0
            for item in bins
        )
        and sum(integer(item.get("count")) for item in bins) == sample.get("chunks_read")
        and sum(integer(item.get("size_bytes")) * integer(item.get("count")) for item in bins) == body
    )


def batch_cpu_identity(result: JsonObject) -> bool:
    batches = object_list(object_value(result.get("client_report")).get("batches"))
    return bool(batches) and all(
        object_value(object_value(batch.get("cpu")).get(role)).get("pid") == result.get(f"{role}_pid")
        for batch in batches
        for role in ("client", "server")
    )


def declared_workload_matches(result: JsonObject) -> bool:
    child = object_value(result.get("client_report"))
    configuration = object_value(child.get("config"))
    case = object_value(result.get("case"))
    count = configuration.get("batches")
    rounds = configuration.get("rounds_per_batch")
    concurrency = case.get("concurrency")
    warmup = configuration.get("warmup_rounds")
    batches = object_list(child.get("batches"))
    if (
        type(count) is not int
        or type(rounds) is not int
        or type(concurrency) is not int
        or type(warmup) is not int
        or count <= 0
        or rounds <= 0
        or concurrency <= 0
        or warmup < 0
    ):
        return False
    return (
        len(batches) == count
        and [batch.get("batch") for batch in batches] == list(range(1, count + 1))
        and all(
            (
                window_workload_matches(batch, configuration, concurrency)
                and batch_workload_matches(batch, integer(batch.get("rounds")), concurrency)
                if object_value(configuration.get("attribution")).get("minimum_duration_s")
                else batch_workload_matches(batch, rounds, concurrency)
            )
            and batch_timing_matches(batch)
            for batch in batches
        )
        and batch_workload_matches(object_value(child.get("warmup")), warmup, concurrency)
        and (
            warmup == 0
            or sample_evidence_complete(object_list(object_value(child.get("warmup")).get("samples")), configuration)
        )
    )


def batch_workload_matches(batch: JsonObject, rounds: int, concurrency: int) -> bool:
    requests = rounds * concurrency
    samples = object_list(batch.get("samples"))
    return (
        batch.get("rounds") == rounds
        and batch.get("requests") == requests
        and len(samples) == requests
        and ([sample.get("stream") for sample in samples] == list(range(1, requests + 1)))
        and not batch.get("errors")
        and batch.get("ok_streams") == requests
    )


def batch_timing_matches(batch: JsonObject) -> bool:
    timing = object_value(batch.get("timing"))
    start = timing.get("load_started_ns")
    finish = timing.get("load_finished_ns")
    duration = number(batch.get("duration_s"))
    finalize = timing.get("digest_finalize_duration_ns")
    return (
        type(start) is int
        and type(finish) is int
        and 0 <= start < finish
        and duration is not None
        and (math.isclose(duration, (finish - start) / 1_000_000_000, rel_tol=1e-12, abs_tol=1e-12))
        and type(finalize) is int
        and finalize >= 0
        and bool(timing.get("clock"))
        and (timing.get("verified_only_after_finalization") is True)
        and all(
            cpu_boundary_matches(object_value(object_value(batch.get("cpu")).get(role)), start, finish)
            for role in ("client", "server")
        )
    )


def cpu_boundary_matches(cpu: JsonObject, load_start: int, load_finish: int) -> bool:
    before, after = object_value(cpu.get("before")), object_value(cpu.get("after"))
    times = [
        before.get("probe_started_ns"),
        before.get("probe_finished_ns"),
        after.get("probe_started_ns"),
        after.get("probe_finished_ns"),
    ]
    if not all(type(value) is int for value in times):
        return False
    start_before, end_before, start_after, end_after = (integer(value) for value in times)
    return (
        0 <= start_before <= end_before <= load_start < load_finish <= start_after <= end_after
        and (before.get("pid") == cpu.get("pid") == after.get("pid"))
        and type(cpu.get("load_boundary_overhang_ns")) is int
        and cpu.get("load_boundary_overhang_ns") == (load_start - start_before + end_after - load_finish)
    )


def gap_quantile(samples: list[JsonObject], fraction: float) -> float | None:
    return quantile(
        [{"gap": gap} for sample in samples for gap in list_value(sample.get("gap_samples_ms"))],
        "gap",
        fraction,
    )


def aggregate_cpu(children: list[JsonObject], role: str) -> JsonObject:
    repeats: list[JsonObject] = []
    unavailable: set[str] = set()
    complete = bool(children)
    for child in children:
        batches = object_list(child.get("batches"))
        observations = [object_value(object_value(batch.get("cpu")).get(role)) for batch in batches]
        complete = (
            complete
            and bool(observations)
            and all(
                (value := number(item.get(key))) is not None and value >= 0
                for item in observations
                for key in ("user_s", "system_s", "total_s")
            )
            and all(not item.get("unavailable_reason") for item in observations)
        )
        verified = sum(integer(batch.get("verified_success_bytes")) for batch in batches)
        wall = sum(number(batch.get("duration_s")) or 0 for batch in batches)
        summary: JsonObject = {}
        for key in ("user_s", "system_s", "total_s"):
            values = [number(item.get(key)) for item in observations]
            summary[key] = (
                sum(value for value in values if value is not None)
                if values and all(value is not None for value in values)
                else None
            )
        total = number(summary.get("total_s"))
        summary["cpu_seconds_per_verified_byte"] = total / verified if total is not None and verified > 0 else None
        summary["cpu_seconds_per_wall_second"] = total / wall if total is not None and wall > 0 else None
        for item in observations:
            missing = item.get("unavailable_reason")
            if missing:
                unavailable.add(str(missing))
        repeats.append(summary)
    return {
        "complete": complete,
        **{
            f"{key}_median": median_optional(number(item.get(key)) for item in repeats)
            for key in (
                "user_s",
                "system_s",
                "total_s",
                "cpu_seconds_per_verified_byte",
                "cpu_seconds_per_wall_second",
            )
        },
        "unavailable": sorted(unavailable),
        "scope": (
            "Per-PID CPU counters bracketing load plus retained boundary probe overhang; "
            "user+system may exceed wall time with multicore work"
        ),
    }


def aggregate_overhead(batches: list[JsonObject]) -> JsonObject:
    observations = [object_value(batch.get("overhead")) for batch in batches]
    return {
        "complete": bool(observations)
        and all(
            item.get("status") == "ok"
            and not item.get("reason")
            and all(
                (value := number(item.get(key))) is not None and value >= 0
                for key in ("scalar_only_s", "sha256_only_s", "combined_s")
            )
            for item in observations
        ),
        "distribution_complete": bool(observations)
        and all(item.get("distribution_complete") is True for item in observations),
        **{
            f"{key}_median": median_optional(number(item.get(key)) for item in observations)
            for key in ("scalar_only_s", "sha256_only_s", "combined_s")
        },
        "reasons": sorted({str(item["reason"]) for item in observations if item.get("reason")}),
        "scope": "separate bounded in-memory replay over observed chunk sizes; no subtraction from primary metrics",
    }


def write_attribution_reports(
    results: list[JsonObject],
    args: BenchmarkArgs,
    config: LifecycleConfig,
    plan: list[LifecycleCase],
) -> None:
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    versions = package_versions(["foghttp", "foghttp-benchmark", "httpx", "psutil", "jinja2"])
    clock = time.get_clock_info("perf_counter")
    processor = platform.processor()
    environment: JsonObject = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": processor or None,
        "processor_unavailable_reason": None
        if processor
        else "platform.processor() did not expose a processor identifier",
        "logical_cpu_count": os.cpu_count(),
        "gc": object_value(object_value(results[0].get("client_report")).get("gc_configuration")) if results else {},
        "clock": {
            "implementation": clock.implementation,
            "resolution_s": clock.resolution,
            "monotonic": clock.monotonic,
        },
        "dependencies": {
            name: version for name, version in versions.items() if name not in {"foghttp", "foghttp-benchmark"}
        },
    }
    conditions = measurement_conditions(config, environment)
    rows = aggregate_attribution_results(results, conditions)
    children = [child_diagnostic(result) for result in results]
    sidecars: list[JsonObject] = []
    runs: list[JsonObject] = []
    for result in results:
        case = object_value(result.get("case"))
        sequence = integer(case.get("sequence"))
        reference = write_raw_sidecar(
            directory,
            f"case-{sequence:03d}.json",
            {"sequence": sequence, "result": result},
            sequence=sequence,
        )
        sidecars.append(reference)
        child = object_value(result.get("client_report"))
        runs.append(
            {
                **{key: value for key, value in result.items() if key not in {"resources", "client_report"}},
                "raw_evidence": reference,
                "client_report": {
                    **{key: value for key, value in child.items() if key not in {"batches", "warmup"}},
                    "batches": [
                        {key: value for key, value in batch.items() if key != "samples"}
                        for batch in object_list(child.get("batches"))
                    ],
                },
            },
        )
    harness = package_sources(["foghttp_benchmark"])["foghttp_benchmark"]
    if harness.get("source_type") == "local-git":
        harness["checkout"] = capture_harness(Path(str(harness["git_root"])))
    metadata: JsonObject = {
        "timestamp": timestamp,
        "python": sys.version,
        "platform": platform.platform(),
        "suite": "response-streaming",
        "profile": "async-bytes",
        "schema_version": ATTRIBUTION_SCHEMA_VERSION,
        "policy_version": ATTRIBUTION_POLICY_VERSION,
        "measurement_scope": MEASUREMENT_SCOPE,
        "timing_scope": TIMING_SCOPE,
        "throughput_scope": "verified-eof-v2",
        "conditions": conditions,
        "condition_fingerprint": condition_fingerprint(conditions),
        "args": vars(args),
        "config": asdict(config),
        "plan": [asdict(case) for case in plan],
        "package_versions": versions,
        "package_sources": package_sources(["foghttp"]),
        "harness_source": harness,
        "isolation": {"mode": "per-lifecycle-case", "children": children},
        "lifecycle": {
            "expected_cases": len(plan),
            "cases": children,
            "plan_matches": [object_value(result.get("case")) for result in results] == [asdict(case) for case in plan],
        },
        "raw_evidence": sidecars,
        "attribution_limits": {
            "native_copy_cost": None,
            "event_loop_wakeups": None,
            "future_completions": None,
            "reason": (
                "Public Python chunk/await observations cannot separately identify "
                "Rust copies, wakeups or Future completions."
            ),
            "cpu": (
                "Per-PID load boundary deltas include HTTP transport, hashing and scalar observations; "
                "endpoint probe overhang is retained raw."
            ),
            "overhead": (
                "Replay is an estimate on observed sizes; "
                "allocator/cache/transport scheduling differ from live streaming."
            ),
            "rss": (
                "Sampled peaks can miss short peaks; stable RSS does not prove all memory bounds or absence of leaks."
            ),
        },
    }
    metadata["raw_evidence_validation"] = inspect_raw_evidence(metadata, directory)
    object_value(metadata["raw_evidence_validation"])["aggregates_match"] = True
    metadata = metadata_with_validity(metadata, rows)
    payload = {"metadata": metadata, "aggregate": rows, "runs": runs}
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    markdown = (
        report_environment()
        .get_template("streaming_attribution_report.md.j2")
        .render(
            timestamp=timestamp,
            aggregate=rows,
            metadata=metadata,
            runs=runs,
        )
    )
    for name in (timestamp, "latest"):
        (directory / f"{name}.json").write_text(encoded)
        (directory / f"{name}.md").write_text(markdown)


def revalidate_attribution_rows(metadata: JsonObject, rows: list[JsonObject], directory: Path) -> JsonObject:
    status = inspect_raw_evidence(metadata, directory)
    status["aggregates_match"] = False
    if status.get("status") != "ok":
        return status
    cases = object_list(object_value(metadata.get("lifecycle")).get("cases"))
    references = object_list(metadata.get("raw_evidence"))
    case_by_sequence = {integer(case.get("sequence")): case for case in cases}
    if len(case_by_sequence) != len(cases) or {integer(item.get("sequence")) for item in references} != set(
        case_by_sequence,
    ):
        return {**status, "status": "invalid", "errors": ["Raw evidence does not match declared fresh cases"]}
    groups: dict[tuple[str, ...], list[JsonObject]] = {}
    for reference in references:
        case = case_by_sequence[integer(reference.get("sequence"))]
        key = tuple(str(case.get(field)) for field in ("mode", "client", "case", "concurrency"))
        groups.setdefault(key, []).append(reference)
    rebuilt: list[JsonObject] = []
    try:
        for group in groups.values():
            # One cell at a time retains at most three bounded fresh-repeat sidecars.
            results = [
                object_value(json.loads((directory / str(item["path"])).read_text())).get("result") for item in group
            ]
            rebuilt.extend(
                aggregate_attribution_results(
                    [object_value(result) for result in results],
                    object_value(metadata.get("conditions")),
                ),
            )
    except (OSError, TypeError, ValueError) as exc:
        return {**status, "status": "invalid", "errors": [f"Raw aggregate recomputation failed: {type(exc).__name__}"]}
    fields = ("mode", "client", "case", "concurrency", "condition_fingerprint")
    equal = sorted(rebuilt, key=lambda row: tuple(str(row.get(field)) for field in fields)) == sorted(
        rows,
        key=lambda row: tuple(str(row.get(field)) for field in fields),
    )
    return {
        **status,
        "status": "ok" if equal else "invalid",
        "aggregates_match": equal,
        "errors": [] if equal else ["Stored aggregate differs from raw per-stream/per-PID evidence"],
    }
