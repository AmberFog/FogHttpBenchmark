__all__ = ("measurement_conditions", "write_attribution_reports")

from dataclasses import asdict
import json
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
from foghttp_benchmark.rendering import ProfileRenderContext, load_report_template, render_profile_markdown
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.streaming.attribution_aggregation import TIMING_SCOPE, aggregate_attribution_results, integer
from foghttp_benchmark.streaming.lifecycle_aggregation import MEASUREMENT_SCOPE, child_diagnostic
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.report_values import object_list, object_value
from foghttp_benchmark.validity.reports import metadata_with_validity


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
    markdown = render_profile_markdown(
        load_report_template("streaming_attribution_report.md.j2"),
        ProfileRenderContext(timestamp=timestamp, aggregate=rows, metadata=metadata, runs=runs),
    )
    for name in (timestamp, "latest"):
        (directory / f"{name}.json").write_text(encoded)
        (directory / f"{name}.md").write_text(markdown)
