__all__ = (
    "aggregate_request_builder_results",
    "write_request_builder_reports",
)

from collections.abc import Iterable
from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES, REQUEST_BUILDER_SUITE
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.request_builder.models import RequestBuilderAggregateRow, RequestBuilderResult
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
        rss_mb_max=max((item.peak_rss_mb or 0.0) for item in items),
        threads_max=max((item.peak_threads or 0) for item in items),
        fds_max=max((item.peak_fds or 0) for item in items),
        errors_total=sum(item.errors for item in items),
        error_types=merge_error_types(item.error_types for item in items),
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


def write_request_builder_reports(
    results: list[RequestBuilderResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
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
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
            ),
            "skipped": skipped,
        },
        aggregate_rows,
    )
    payload = {
        "metadata": metadata_payload,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_request_builder_markdown_report(timestamp, aggregate, skipped, args, metadata_payload["validity"])
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_request_builder_markdown_report(
    timestamp: str,
    aggregate: list[RequestBuilderAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    validity: object,
) -> str:
    template = report_environment().get_template("request_builder_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
        validity=validity,
    )


def kind_order(kind: str) -> int:
    order = {
        "build": 0,
        "send-prepared": 1,
    }
    return order.get(kind, 99)
