__all__ = ("write_resource_reports",)

from dataclasses import asdict
from pathlib import Path
import platform
import sys
import time

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, ResourceBackpressureResult
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.resource.reporting.aggregation import aggregate_resource_results
from foghttp_benchmark.resource_metrics import RESOURCE_METRIC_SCHEMA_VERSION
from foghttp_benchmark.validity.reports import metadata_with_validity


def write_resource_reports(
    results: list[ResourceBackpressureResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_resource_results(results)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": args.suite,
            "timing_scope": current_timing_scope(args.suite),
            "resource_metric_schema_version": RESOURCE_METRIC_SCHEMA_VERSION,
            "args": vars(args),
            "resource_cases": sorted({result.scenario for result in results}),
            "package_versions": package_versions(),
            "skipped": skipped,
        },
        aggregate_rows,
    )
    payload: dict[str, object] = {
        "metadata": metadata_payload,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    markdown = render_suite_markdown(
        load_report_template("resource_report.md.j2"),
        SuiteRenderContext(
            timestamp=timestamp,
            args=args,
            aggregate=aggregate,
            skipped=skipped,
            validity=metadata_payload["validity"],
            environment=RenderEnvironment(
                python_version=platform.python_version(),
                platform_name=platform.platform(),
            ),
        ),
    )
    publish_report(output_dir, timestamp, payload, markdown)
