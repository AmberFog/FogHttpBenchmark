__all__ = ("aggregate_lifecycle_results", "write_lifecycle_reports")

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import cast

from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.provenance import capture_harness, package_sources
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.validity.lifecycle import (
    LIFECYCLE_MIN_VARIATION_REPETITIONS,
    LIFECYCLE_VARIATION_LIMIT_PERCENT,
)
from foghttp_benchmark.validity.reports import metadata_with_validity


MEASUREMENT_SCOPE = "separate-client-server-pids-v1"


def aggregate_lifecycle_results(results: list[JsonObject]) -> list[JsonObject]:
    grouped: dict[tuple[str, str, str, int], list[JsonObject]] = defaultdict(list)
    for result in results:
        case = object_value(result.get("case"))
        key = (
            str(case.get("mode", "")),
            str(case.get("client", "")),
            str(case.get("case", "")),
            int_value(case.get("concurrency")),
        )
        grouped[key].append(result)
    return [aggregate_case(key, items) for key, items in sorted(grouped.items())]


def aggregate_case(key: tuple[str, str, str, int], results: list[JsonObject]) -> JsonObject:
    mode, client, case, concurrency = key
    children = [object_value(result.get("client_report")) for result in results]
    batches = [batch for child in children for batch in object_list(child.get("batches"))]
    samples = [sample for batch in batches for sample in object_list(batch.get("samples"))]
    rates = [rate for child in children if (rate := repeat_rate(child)) is not None]
    durations = [duration for child in children if (duration := repeat_duration(child)) is not None]
    errors = sum(len(object_list(child.get("errors"))) for child in children)
    warmup_errors = sum(len(object_list(object_value(child.get("warmup")).get("errors"))) for child in children)
    controls = [object_value(child.get("controls")) for child in children]
    phase_cpu: dict[tuple[str, str, str], list[JsonObject]] = defaultdict(list)
    phase_resources: dict[tuple[str, str], list[JsonObject]] = defaultdict(list)
    for result in results:
        resources = object_value(result.get("resources"))
        for delta in object_list(resources.get("cpu_phase_deltas")):
            phase_cpu[(str(delta.get("role")), str(delta.get("from_phase")), str(delta.get("to_phase")))].append(delta)
        for phase in object_list(resources.get("phases")):
            for role in ("client", "server"):
                sample = object_value(phase.get(role))
                if sample:
                    phase_resources[(role, str(phase.get("phase")))].append(sample)
    return {
        "profile": "lifecycle",
        "measurement_scope": MEASUREMENT_SCOPE,
        "configuration": object_value(children[0].get("config")) if children else {},
        "configurations_match": bool(children)
        and all(child.get("config") == children[0].get("config") for child in children),
        "mode": mode,
        "client": client,
        "case": case,
        "read": "bytes",
        "consume": "all" if case == "stream-1m" else "first-chunk",
        "concurrency": concurrency,
        "request_limit": concurrency,
        "repeats": len(results),
        "successful_repeats": sum(
            child.get("status") == "ok" and not result.get("failure")
            for result, child in zip(results, children, strict=True)
        ),
        "batch_count": len(batches),
        "ok_streams_total": sum(int_value(batch.get("ok_streams")) for batch in batches),
        "bytes_read_total": sum(int_value(batch.get("bytes_read_total")) for batch in batches),
        "expected_aborts_total": sum(
            int_value(held.get("expected_aborts"))
            for control in controls
            if (held := object_value(control.get("held_tail"))).get("status") == "ok"
        ),
        "errors_total": errors,
        "warmup_errors_total": warmup_errors,
        "failed_cases": sum(
            bool(result.get("failure")) or child.get("status") != "ok"
            for result, child in zip(results, children, strict=True)
        ),
        "ok_streams_s_median": median_optional(rates),
        "streams_s_cv_percent": cv_optional(rates),
        "duration_s_cv_percent": cv_optional(durations),
        "variation_sample_count": len(rates),
        "variation_limit_percent": LIFECYCLE_VARIATION_LIMIT_PERCENT,
        "p50_ms_median": repeat_latency_median(children, 0.5),
        "p95_ms_median": repeat_latency_median(children, 0.95),
        "p99_ms_median": repeat_latency_median(children, 0.99),
        "first_item_p95_ms": quantile(samples, "first_item_ms", 0.95),
        "close_return_p95_ms": quantile(samples, "close_return_ms", 0.95),
        "first_chunk_bytes_min": minimum_optional(number(sample.get("first_chunk_bytes")) for sample in samples),
        "first_chunk_bytes_max": maximum_optional(number(sample.get("first_chunk_bytes")) for sample in samples),
        "recovery_p95_ms": quantile(
            [
                {"latency": latency}
                for control in controls
                for latency in list_value(object_value(control.get("recovery")).get("latencies_ms"))
            ],
            "latency",
            0.95,
        ),
        "client_construction_ms_median": median_optional(
            number(child.get("client_construction_ms")) for child in children
        ),
        "client_close_ms_median": median_optional(number(child.get("client_close_ms")) for child in children),
        "resources": {role: aggregate_resources(results, children, role) for role in ("client", "server")},
        "cpu_phase_deltas": [
            {
                "role": role,
                "from_phase": start,
                "to_phase": end,
                "user_s_median": median_optional(number(item.get("user_s")) for item in items),
                "system_s_median": median_optional(number(item.get("system_s")) for item in items),
                "unavailable": aggregate_unavailability(items, ("user_s", "system_s")),
            }
            for (role, start, end), items in sorted(phase_cpu.items())
        ],
        "phase_resources": [
            {
                "role": role,
                "phase": phase,
                **{
                    f"{metric}_median": median_optional(number(item.get(metric)) for item in items)
                    for metric in ("rss_bytes", "threads", "fds")
                },
                "unavailable": aggregate_unavailability(items, ("rss_bytes", "threads", "fds")),
            }
            for (role, phase), items in sorted(phase_resources.items())
        ],
    }


def aggregate_resources(results: list[JsonObject], children: list[JsonObject], role: str) -> JsonObject:
    peaks = [
        object_value(object_value(object_value(result.get("resources")).get("sampled_peaks")).get(role))
        for result in results
    ]
    lifetime = (
        [phase.get("lifetime_high_water_rss_bytes") for child in children for phase in object_list(child.get("phases"))]
        if role == "client"
        else []
    )
    return {
        "scope": "one PID per fresh repetition",
        "rss_unit": "bytes",
        "sampled_peak_rss_bytes_max": maximum_optional(number(peak.get("rss_bytes")) for peak in peaks),
        "sampled_peak_threads_max": maximum_optional(number(peak.get("threads")) for peak in peaks),
        "sampled_peak_fds_max": maximum_optional(number(peak.get("fds")) for peak in peaks),
        "lifetime_high_water_rss_bytes_max": maximum_optional(number(value) for value in lifetime),
        "lifetime_high_water_unavailable_reason": None
        if role == "client" and any(number(value) is not None for value in lifetime)
        else "No worker lifetime high-water observation for this role.",
        "unavailable": {
            metric: resource_unavailable_reasons(results, role, metric) for metric in ("rss_bytes", "threads", "fds")
        },
    }


def resource_unavailable_reasons(results: list[JsonObject], role: str, metric: str) -> list[str]:
    reasons: set[str] = set()
    for result in results:
        resources = object_value(result.get("resources"))
        peak = object_value(object_value(resources.get("sampled_peaks")).get(role))
        if number(peak.get(metric)) is not None:
            continue
        observed = {
            str(reason)
            for sample in object_list(resources.get("samples"))
            if sample.get("role") == role
            and (reason := object_value(sample.get("unavailable")).get(metric)) is not None
        }
        reasons.update(observed or {"No available parent-owned sample for this metric in this repetition."})
    return sorted(reasons)


def aggregate_unavailability(items: list[JsonObject], metrics: tuple[str, ...]) -> dict[str, list[str]]:
    return {
        metric: sorted(
            {
                str(object_value(item.get("unavailable")).get(metric) or "No observation for this metric.")
                for item in items
                if number(item.get(metric)) is None
            },
        )
        for metric in metrics
    }


def repeat_duration(child: JsonObject) -> float | None:
    durations = [number(batch.get("duration_s")) for batch in object_list(child.get("batches"))]
    if not durations or any(value is None for value in durations):
        return None
    return sum(value for value in durations if value is not None)


def repeat_rate(child: JsonObject) -> float | None:
    duration = repeat_duration(child)
    if duration is None or duration <= 0:
        return None
    return sum(int_value(batch.get("ok_streams")) for batch in object_list(child.get("batches"))) / duration


def repeat_latency_median(children: list[JsonObject], fraction: float) -> float | None:
    return median_optional(
        quantile(
            [sample for batch in object_list(child.get("batches")) for sample in object_list(batch.get("samples"))],
            "duration_ms",
            fraction,
        )
        for child in children
    )


def write_lifecycle_reports(
    results: list[JsonObject],
    args: BenchmarkArgs,
    config: LifecycleConfig,
    plan: list[LifecycleCase],
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_lifecycle_results(results)
    children = [child_diagnostic(result) for result in results]
    harness_source = package_sources(["foghttp_benchmark"])["foghttp_benchmark"]
    if harness_source.get("source_type") == "local-git":
        harness_source["checkout"] = capture_harness(Path(str(harness_source["git_root"])))
    metadata = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "suite": "response-streaming",
            "profile": "lifecycle",
            "measurement_scope": MEASUREMENT_SCOPE,
            "resource_units": {
                "rss": "bytes",
                "cpu_user": "seconds",
                "cpu_system": "seconds",
                "monotonic": "nanoseconds",
                "fds": "count",
                "threads": "count",
            },
            "sampling": {
                "owner": "parent process outside client event loop",
                "interval_s": config.sample_interval_s,
                "maximum_samples_per_case": config.max_samples,
                "limitations": (
                    "Sampled peaks can miss shorter peaks; probes have nonzero overhead. "
                    "Stable RSS does not prove bounded memory or absence of leaks."
                ),
            },
            "config": asdict(config),
            "args": vars(args),
            "plan": [asdict(case) for case in plan],
            "package_versions": package_versions(["foghttp", "foghttp-benchmark", "httpx", "psutil", "jinja2"]),
            "package_sources": package_sources(["foghttp"]),
            "harness_source": harness_source,
            "isolation": {"mode": "per-lifecycle-case", "children": children},
            "lifecycle": {
                "expected_cases": len(plan),
                "cases": children,
                "plan_matches": [object_value(result.get("case")) for result in results]
                == [asdict(case) for case in plan],
            },
            "comparison_policy": (
                "Early close and EOF deliver different byte counts. Throughput is comparable only within an "
                "identical lifecycle case and configuration; no competitive ranking is produced."
            ),
        },
        aggregate,
    )
    payload = {"metadata": metadata, "aggregate": aggregate, "runs": results}
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    markdown = (
        report_environment()
        .get_template("streaming_lifecycle_report.md.j2")
        .render(timestamp=timestamp, aggregate=aggregate, metadata=metadata, runs=results)
    )
    for name in (timestamp, "latest"):
        (output_dir / f"{name}.json").write_text(json_text)
        (output_dir / f"{name}.md").write_text(markdown)


def child_diagnostic(result: JsonObject) -> JsonObject:
    child = object_value(result.get("client_report"))
    metadata = object_value(child.get("metadata"))
    case = object_value(result.get("case"))
    pids = [result.get(key) for key in ("parent_pid", "client_pid", "server_pid")]
    resources = object_value(result.get("resources"))
    samples = object_list(resources.get("samples"))
    sample_pid_mismatch = any(
        sample.get("role") not in ("client", "server") or sample.get("pid") != result.get(f"{sample.get('role')}_pid")
        for sample in samples
    )
    return {
        **case,
        "scenario": case.get("case"),
        "returncode": result.get("returncode"),
        "server_returncode": result.get("server_returncode"),
        "report_path": result.get("report_path"),
        "failure": result.get("failure"),
        "failures": result.get("failures", []),
        "parent_pid": pids[0],
        "client_pid": pids[1],
        "server_pid": pids[2],
        "pid_identity_valid": all(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 for pid in pids)
        and len(set(pids)) == len(pids)
        and child.get("worker_pid") == result.get("client_pid")
        and not sample_pid_mismatch,
        "worker_status": child.get("status"),
        "controls": child.get("controls"),
        "errors": child.get("errors"),
        "resources_truncated": resources.get("truncated"),
        "resource_samples_present": {sample.get("role") for sample in samples} == {"client", "server"},
        "research_provenance": metadata.get("research_provenance"),
        "package_sources": metadata.get("package_sources"),
    }


def object_value(value: object) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[JsonObject]:
    return [cast("JsonObject", item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def number(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def int_value(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def median_optional(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.median(present) if present else None


def maximum_optional(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def minimum_optional(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def quantile(samples: list[JsonObject], key: str, fraction: float) -> float | None:
    present = sorted(value for sample in samples if (value := number(sample.get(key))) is not None)
    return present[round(fraction * (len(present) - 1))] if present else None


def cv_optional(values: list[float]) -> float | None:
    if len(values) < LIFECYCLE_MIN_VARIATION_REPETITIONS or statistics.mean(values) == 0:
        return None
    return statistics.stdev(values) / statistics.mean(values) * 100
