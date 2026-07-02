__all__ = (
    "aggregate_proxy_connect_results",
    "redacted_proxy_url",
    "write_proxy_connect_reports",
)

from collections.abc import Iterable
from dataclasses import asdict, replace
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from urllib.parse import SplitResult, urlsplit, urlunsplit

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES, PROXY_CONNECT_SUITE
from foghttp_benchmark.models import BenchmarkArgs, ClientStatKey
from foghttp_benchmark.proxy_connect.models import ProxyConnectAggregateRow, ProxyConnectResult
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.validity.reports import metadata_with_validity


def aggregate_proxy_connect_results(results: list[ProxyConnectResult]) -> list[ProxyConnectAggregateRow]:
    grouped: dict[tuple[str, str, str, str, str, str, str, int, int], list[ProxyConnectResult]] = {}
    for result in results:
        key = (
            result.mode,
            result.client,
            result.case,
            result.group,
            result.target_scheme,
            result.config,
            result.lifecycle,
            result.concurrency,
            result.request_limit,
        )
        grouped.setdefault(key, []).append(result)

    rows = [
        build_aggregate_row(key, items)
        for key, items in sorted(grouped.items(), key=lambda item: aggregate_sort_key(item[0]))
    ]
    return rows_with_direct_ratios(rows)


def aggregate_sort_key(
    key: tuple[str, str, str, str, str, str, str, int, int],
) -> tuple[str, str, str, int, int, int, str, str]:
    mode, client, case, group, _target_scheme, config, lifecycle, concurrency, request_limit = key
    return (
        mode,
        client,
        group,
        concurrency,
        request_limit,
        config_order(config),
        lifecycle,
        case,
    )


def build_aggregate_row(
    key: tuple[str, str, str, str, str, str, str, int, int],
    items: list[ProxyConnectResult],
) -> ProxyConnectAggregateRow:
    mode, client, case, group, target_scheme, config, lifecycle, concurrency, request_limit = key
    requests_total = sum(item.requests for item in items)
    errors_total = sum(item.errors for item in items)
    return ProxyConnectAggregateRow(
        mode=mode,
        client=client,
        case=case,
        group=group,
        target_scheme=target_scheme,
        config=config,
        lifecycle=lifecycle,
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
        direct_ratio=None,
        p50_ms_median=statistics.median(item.p50_ms for item in items),
        p95_ms_median=statistics.median(item.p95_ms for item in items),
        p99_ms_median=statistics.median(item.p99_ms for item in items),
        rss_mb_max=max((item.peak_rss_mb or 0.0) for item in items),
        threads_max=max((item.peak_threads or 0) for item in items),
        fds_max=max((item.peak_fds or 0) for item in items),
        measured_proxy_http_requests_max=max(item.measured_proxy.http_requests for item in items),
        measured_proxy_connect_requests_max=max(item.measured_proxy.connect_requests for item in items),
        total_proxy_http_requests_max=max(item.total_proxy.http_requests for item in items),
        total_proxy_connect_requests_max=max(item.total_proxy.connect_requests for item in items),
        proxy_authorization_headers_max=max(item.total_proxy.proxy_authorization_headers for item in items),
        final_connections_opened_max=client_stat_max(items, "connections_opened"),
        final_connections_reused_max=client_stat_max(items, "connections_reused"),
        final_connections_closed_max=client_stat_max(items, "connections_closed"),
        final_connections_aborted_max=client_stat_max(items, "connections_aborted"),
        error_types=merge_error_types(item.error_types for item in items),
    )


def rows_with_direct_ratios(rows: list[ProxyConnectAggregateRow]) -> list[ProxyConnectAggregateRow]:
    baselines = {
        (row.mode, row.client, row.target_scheme, row.concurrency): row.ok_req_s_median
        for row in rows
        if row.config == "direct" and row.lifecycle == "reused-client"
    }
    return [
        replace(
            row,
            direct_ratio=baseline_ratio(
                row.ok_req_s_median,
                baselines.get((row.mode, row.client, row.target_scheme, row.concurrency)),
            ),
        )
        for row in rows
    ]


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def baseline_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


def client_stat_max(items: list[ProxyConnectResult], key: ClientStatKey) -> int | None:
    values = [item.client_stats[key] for item in items if item.client_stats is not None and key in item.client_stats]
    return max(values) if values else None


def merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for errors in values:
        for key, count in errors.items():
            merged[key] = merged.get(key, 0) + count
    return merged


def redacted_proxy_url(value: str) -> str:
    parts = urlsplit(value)
    if "@" not in parts.netloc:
        return value
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"***:***@{host}{port}"
    return urlunsplit(SplitResult(parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def write_proxy_connect_reports(
    results: list[ProxyConnectResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    *,
    proxy_url: str,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_proxy_connect_results(results)
    redacted_proxy = redacted_proxy_url(proxy_url)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 + HTTPS loopback origin with local HTTP proxy",
            "suite": PROXY_CONNECT_SUITE,
            "args": vars(args),
            "proxy_url": redacted_proxy,
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "jinja2", "psutil", "rich", "typer"],
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

    markdown = render_proxy_connect_markdown_report(
        timestamp,
        aggregate,
        skipped,
        args,
        proxy_url=redacted_proxy,
        validity=metadata_payload["validity"],
    )
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_proxy_connect_markdown_report(
    timestamp: str,
    aggregate: list[ProxyConnectAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    *,
    proxy_url: str,
    validity: object,
) -> str:
    template = report_environment().get_template("proxy_connect_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        proxy_url=proxy_url,
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
        validity=validity,
    )


def config_order(config: str) -> int:
    order = {
        "direct": 0,
        "explicit": 1,
        "trust-env": 2,
    }
    return order.get(config, 99)
