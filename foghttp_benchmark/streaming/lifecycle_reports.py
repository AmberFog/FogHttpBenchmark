__all__ = ("write_lifecycle_reports",)

from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys
import time

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.provenance import capture_harness, package_sources
from foghttp_benchmark.rendering import ProfileRenderContext, load_report_template, render_profile_markdown
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.streaming.lifecycle_aggregation import (
    MEASUREMENT_SCOPE,
    aggregate_lifecycle_results,
    child_diagnostic,
)
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.report_values import object_value
from foghttp_benchmark.validity.reports import metadata_with_validity


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
            "timing_scope": current_timing_scope("response-streaming", "lifecycle"),
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
    markdown = render_profile_markdown(
        load_report_template("streaming_lifecycle_report.md.j2"),
        ProfileRenderContext(timestamp=timestamp, aggregate=aggregate, metadata=metadata, runs=results),
    )
    for name in (timestamp, "latest"):
        (output_dir / f"{name}.json").write_text(json_text)
        (output_dir / f"{name}.md").write_text(markdown)
