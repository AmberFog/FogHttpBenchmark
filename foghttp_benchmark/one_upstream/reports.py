__all__ = (
    "aggregate_one_upstream_results",
    "write_one_upstream_reports",
)

from collections.abc import Iterable
from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES, ONE_UPSTREAM_SUITE
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.one_upstream.models import OneUpstreamAggregateRow, OneUpstreamResult
from foghttp_benchmark.reports import package_versions, report_environment


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
        error_rate_percent=(errors_total / requests_total) * 100 if requests_total else 0.0,
        ok_req_s_median=statistics.median(item.ok_requests_per_second for item in items),
        req_s_median=statistics.median(item.requests_per_second for item in items),
        req_s_cv_percent=coefficient_of_variation([item.requests_per_second for item in items]),
        baseline_ratio=None,
        p50_ms_median=statistics.median(item.p50_ms for item in items),
        p95_ms_median=statistics.median(item.p95_ms for item in items),
        p99_ms_median=statistics.median(item.p99_ms for item in items),
        rss_mb_max=max((item.peak_rss_mb or 0.0) for item in items),
        threads_max=max((item.peak_threads or 0) for item in items),
        fds_max=max((item.peak_fds or 0) for item in items),
        error_types=merge_error_types(item.error_types for item in items),
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


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for errors in values:
        for key, count in errors.items():
            merged[key] = merged.get(key, 0) + count
    return merged


def write_one_upstream_reports(
    results: list[OneUpstreamResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_one_upstream_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": ONE_UPSTREAM_SUITE,
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
            ),
            "skipped": skipped,
        },
        "aggregate": [asdict(row) for row in aggregate],
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_one_upstream_markdown_report(timestamp, aggregate, skipped, args)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_one_upstream_markdown_report(
    timestamp: str,
    aggregate: list[OneUpstreamAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("one_upstream_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )


def profile_order(profile: str) -> int:
    order = {
        "direct": 0,
        "base-url": 1,
        "defaults": 2,
        "prepared": 3,
    }
    return order.get(profile, 99)
