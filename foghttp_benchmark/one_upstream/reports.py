__all__ = (
    "aggregate_one_upstream_results",
    "write_one_upstream_reports",
)

from dataclasses import asdict, replace
import os
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import ONE_UPSTREAM_SUITE
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.one_upstream.models import OneUpstreamAggregateRow, OneUpstreamResult
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
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.run_settling import RunSettlingConfig, run_settling_config
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types
from foghttp_benchmark.validity.reports import metadata_with_validity


def aggregate_one_upstream_results(results: list[OneUpstreamResult]) -> list[OneUpstreamAggregateRow]:
    grouped: dict[tuple[str, str, str, str, str, int, int], list[OneUpstreamResult]] = {}
    for result in results:
        key = (
            result.mode,
            result.client,
            result.case,
            result.group,
            result.profile,
            result.concurrency,
            result.request_limit,
        )
        grouped.setdefault(key, []).append(result)

    rows = [
        build_aggregate_row(key, items)
        for key, items in sorted(grouped.items(), key=lambda item: aggregate_sort_key(item[0]))
    ]
    return rows_with_baseline_ratios(rows)


def aggregate_sort_key(key: tuple[str, str, str, str, str, int, int]) -> tuple[str, str, str, int, int, str, int]:
    mode, client, case, group, profile, concurrency, request_limit = key
    return (mode, client, group, concurrency, profile_order(profile), case, request_limit)


def build_aggregate_row(
    key: tuple[str, str, str, str, str, int, int],
    items: list[OneUpstreamResult],
) -> OneUpstreamAggregateRow:
    mode, client, case, group, profile, concurrency, request_limit = key
    requests_total = sum(item.requests for item in items)
    errors_total = sum(item.errors for item in items)
    return OneUpstreamAggregateRow(
        mode=mode,
        client=client,
        case=case,
        group=group,
        profile=profile,
        concurrency=concurrency,
        request_limit=request_limit,
        requests=items[0].requests,
        repeats=len(items),
        ok_requests_total=sum(item.ok_requests for item in items),
        errors_total=errors_total,
        warmup_errors_total=sum(item.warmup_errors for item in items),
        warmup_error_types=merge_error_types(item.warmup_error_types for item in items),
        error_rate_percent=(errors_total / requests_total) * 100 if requests_total else 0.0,
        ok_req_s_median=statistics.median(item.ok_requests_per_second for item in items),
        req_s_median=statistics.median(item.requests_per_second for item in items),
        req_s_cv_percent=coefficient_of_variation([item.requests_per_second for item in items]),
        baseline_ratio=None,
        p50_ms_median=statistics.median(item.p50_ms for item in items),
        p95_ms_median=statistics.median(item.p95_ms for item in items),
        p99_ms_median=statistics.median(item.p99_ms for item in items),
        rss_mb_max=optional_resource_max(item.peak_rss_mb for item in items),
        threads_max=optional_resource_max(item.peak_threads for item in items),
        fds_max=optional_resource_max(item.peak_fds for item in items),
        error_types=merge_error_types(item.error_types for item in items),
        resource_coverage=resource_coverage(
            {
                "rss_mb_max": [item.peak_rss_mb for item in items],
                "threads_max": [item.peak_threads for item in items],
                "fds_max": [item.peak_fds for item in items],
            },
        ),
    )


def rows_with_baseline_ratios(rows: list[OneUpstreamAggregateRow]) -> list[OneUpstreamAggregateRow]:
    baselines = {
        (row.mode, row.client, row.group, row.concurrency): row.ok_req_s_median
        for row in rows
        if row.profile == "direct"
    }
    return [
        replace(
            row,
            baseline_ratio=baseline_ratio(
                row.ok_req_s_median,
                baselines.get((row.mode, row.client, row.group, row.concurrency)),
            ),
        )
        for row in rows
    ]


def baseline_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


def write_one_upstream_reports(
    results: list[OneUpstreamResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    *,
    settling_config: RunSettlingConfig | None = None,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    actual_settling_config = settling_config or run_settling_config(os.environ)
    aggregate = aggregate_one_upstream_results(results)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": ONE_UPSTREAM_SUITE,
            "timing_scope": current_timing_scope(ONE_UPSTREAM_SUITE),
            "resource_metric_schema_version": RESOURCE_METRIC_SCHEMA_VERSION,
            "args": vars(args),
            "package_versions": package_versions(),
            "run_settling": {
                "cooldown_s": actual_settling_config.cooldown_s,
                "opened_connection_threshold": actual_settling_config.opened_connection_threshold,
            },
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
        load_report_template("one_upstream_report.md.j2"),
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


def profile_order(profile: str) -> int:
    order = {
        "direct": 0,
        "base-url": 1,
        "defaults": 2,
        "prepared": 3,
    }
    return order.get(profile, 99)
