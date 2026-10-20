__all__ = (
    "ClientCreationAggregateRow",
    "aggregate_creation_results",
    "write_creation_reports",
)

from dataclasses import asdict, dataclass, field
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, ClientCreationResult
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.resource_metrics import (
    RESOURCE_METRIC_SCHEMA_VERSION,
    ResourceCoverage,
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.statistics import coefficient_of_variation
from foghttp_benchmark.validity.reports import metadata_with_validity


@dataclass(frozen=True, slots=True)
class ClientCreationAggregateRow:
    mode: str
    client: str
    scenario: str
    client_count: int
    iterations: int
    repeats: int
    duration_ms_median: float
    ops_s_median: float
    ops_s_cv_percent: float
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    close_p50_ms_median: float | None
    close_p95_ms_median: float | None
    peak_rss_delta_mb_max: float | None
    end_rss_delta_mb_max: float | None
    peak_threads_delta_max: int | None
    end_threads_delta_max: int | None
    peak_fds_delta_max: int | None
    end_fds_delta_max: int | None
    errors_total: int
    resource_coverage: ResourceCoverage = field(default_factory=dict)


def aggregate_creation_results(results: list[ClientCreationResult]) -> list[ClientCreationAggregateRow]:
    grouped: dict[tuple[str, str, str, int, int], list[ClientCreationResult]] = {}
    for result in results:
        key = (result.mode, result.client, result.scenario, result.client_count, result.iterations)
        grouped.setdefault(key, []).append(result)

    rows: list[ClientCreationAggregateRow] = []
    for (mode, client, scenario, client_count, iterations), items in sorted(grouped.items()):
        rows.append(
            ClientCreationAggregateRow(
                mode=mode,
                client=client,
                scenario=scenario,
                client_count=client_count,
                iterations=iterations,
                repeats=len(items),
                duration_ms_median=statistics.median(item.duration_s * 1000 for item in items),
                ops_s_median=statistics.median(item.operations_per_second for item in items),
                ops_s_cv_percent=coefficient_of_variation(
                    [item.operations_per_second for item in items],
                ),
                p50_ms_median=statistics.median(item.p50_ms for item in items),
                p95_ms_median=statistics.median(item.p95_ms for item in items),
                p99_ms_median=statistics.median(item.p99_ms for item in items),
                close_p50_ms_median=optional_median([item.close_p50_ms for item in items]),
                close_p95_ms_median=optional_median([item.close_p95_ms for item in items]),
                peak_rss_delta_mb_max=optional_resource_max(item.peak_rss_delta_mb for item in items),
                end_rss_delta_mb_max=optional_resource_max(item.end_rss_delta_mb for item in items),
                peak_threads_delta_max=optional_resource_max(item.peak_threads_delta for item in items),
                end_threads_delta_max=optional_resource_max(item.end_threads_delta for item in items),
                peak_fds_delta_max=optional_resource_max(item.peak_fds_delta for item in items),
                end_fds_delta_max=optional_resource_max(item.end_fds_delta for item in items),
                errors_total=sum(item.errors for item in items),
                resource_coverage=resource_coverage(
                    {
                        "peak_rss_delta_mb_max": [item.peak_rss_delta_mb for item in items],
                        "end_rss_delta_mb_max": [item.end_rss_delta_mb for item in items],
                        "peak_threads_delta_max": [item.peak_threads_delta for item in items],
                        "end_threads_delta_max": [item.end_threads_delta for item in items],
                        "peak_fds_delta_max": [item.peak_fds_delta for item in items],
                        "end_fds_delta_max": [item.end_fds_delta for item in items],
                    },
                ),
            ),
        )
    return rows


def optional_median(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.median(present) if present else None


def write_creation_reports(
    results: list[ClientCreationResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_creation_results(results)
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
        load_report_template("creation_report.md.j2"),
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
