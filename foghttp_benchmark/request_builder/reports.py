__all__ = (
    "aggregate_request_builder_results",
    "write_request_builder_reports",
)

from dataclasses import asdict, replace
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import REQUEST_BUILDER_SUITE
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.request_builder.models import RequestBuilderAggregateRow, RequestBuilderResult
from foghttp_benchmark.resource_metrics import (
    RESOURCE_METRIC_SCHEMA_VERSION,
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types
from foghttp_benchmark.validity.reports import metadata_with_validity


def aggregate_request_builder_results(results: list[RequestBuilderResult]) -> list[RequestBuilderAggregateRow]:
    grouped: dict[tuple[str, str, str, str, str, str, int], list[RequestBuilderResult]] = {}
    for result in results:
        key = (
            result.mode,
            result.client,
            result.case,
            result.group,
            result.kind,
            result.profile,
            result.iterations,
        )
        grouped.setdefault(key, []).append(result)

    rows = [
        build_aggregate_row(key, items)
        for key, items in sorted(grouped.items(), key=lambda item: aggregate_sort_key(item[0]))
    ]
    return rows_with_baseline_ratios(rows)


def aggregate_sort_key(key: tuple[str, str, str, str, str, str, int]) -> tuple[str, str, int, str, str, int]:
    mode, client, case, group, kind, _profile, iterations = key
    return (mode, client, kind_order(kind), group, case, iterations)


def build_aggregate_row(
    key: tuple[str, str, str, str, str, str, int],
    items: list[RequestBuilderResult],
) -> RequestBuilderAggregateRow:
    mode, client, case, group, kind, profile, iterations = key
    return RequestBuilderAggregateRow(
        mode=mode,
        client=client,
        case=case,
        group=group,
        kind=kind,
        profile=profile,
        iterations=iterations,
        repeats=len(items),
        duration_ms_median=statistics.median(item.duration_s * 1000 for item in items),
        ops_s_median=statistics.median(item.operations_per_second for item in items),
        ops_s_cv_percent=coefficient_of_variation([item.operations_per_second for item in items]),
        baseline_ratio=None,
        p50_ms_median=statistics.median(item.p50_ms for item in items),
        p95_ms_median=statistics.median(item.p95_ms for item in items),
        p99_ms_median=statistics.median(item.p99_ms for item in items),
        rss_mb_max=optional_resource_max(item.peak_rss_mb for item in items),
        threads_max=optional_resource_max(item.peak_threads for item in items),
        fds_max=optional_resource_max(item.peak_fds for item in items),
        errors_total=sum(item.errors for item in items),
        error_types=merge_error_types(item.error_types for item in items),
        resource_coverage=resource_coverage(
            {
                "rss_mb_max": [item.peak_rss_mb for item in items],
                "threads_max": [item.peak_threads for item in items],
                "fds_max": [item.peak_fds for item in items],
            },
        ),
    )


def rows_with_baseline_ratios(rows: list[RequestBuilderAggregateRow]) -> list[RequestBuilderAggregateRow]:
    baselines = {
        (row.mode, row.client): row.ops_s_median for row in rows if row.kind == "build" and row.case == "absolute-url"
    }
    return [
        replace(
            row,
            baseline_ratio=baseline_ratio(row.ops_s_median, baselines.get((row.mode, row.client)))
            if row.kind == "build"
            else None,
        )
        for row in rows
    ]


def baseline_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


def write_request_builder_reports(
    results: list[RequestBuilderResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_request_builder_results(results)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "none for build cases; local asyncio HTTP/1.1 loopback server for send-prepared cases",
            "suite": REQUEST_BUILDER_SUITE,
            "timing_scope": current_timing_scope(REQUEST_BUILDER_SUITE),
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
        load_report_template("request_builder_report.md.j2"),
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


def kind_order(kind: str) -> int:
    order = {
        "build": 0,
        "send-prepared": 1,
    }
    return order.get(kind, 99)
