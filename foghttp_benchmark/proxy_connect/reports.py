__all__ = (
    "aggregate_proxy_connect_results",
    "redacted_proxy_url",
    "write_proxy_connect_reports",
)

from dataclasses import asdict, replace
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

from foghttp_benchmark.constants import PROXY_CONNECT_SUITE
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, ClientStatKey
from foghttp_benchmark.proxy_connect.finalization import finalize_proxy_connect_rows
from foghttp_benchmark.proxy_connect.models import ProxyConnectAggregateRow, ProxyConnectResult
from foghttp_benchmark.rendering import (
    ProxyRenderContext,
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_proxy_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.resource_metrics import (
    RESOURCE_METRIC_SCHEMA_VERSION,
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types
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
    stat_keys: tuple[ClientStatKey, ...] = (
        "connections_opened",
        "connections_reused",
        "connections_closed",
        "connections_aborted",
    )
    stats = {key: client_stat_values(items, key) for key in stat_keys}
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
        rss_mb_max=optional_resource_max(item.peak_rss_mb for item in items),
        threads_max=optional_resource_max(item.peak_threads for item in items),
        fds_max=optional_resource_max(item.peak_fds for item in items),
        measured_proxy_http_requests_max=max(item.measured_proxy.http_requests for item in items),
        measured_proxy_connect_requests_max=max(item.measured_proxy.connect_requests for item in items),
        total_proxy_http_requests_max=max(item.total_proxy.http_requests for item in items),
        total_proxy_connect_requests_max=max(item.total_proxy.connect_requests for item in items),
        proxy_authorization_headers_max=max(item.total_proxy.proxy_authorization_headers for item in items),
        final_connections_opened_max=optional_resource_max(stats["connections_opened"]),
        final_connections_reused_max=optional_resource_max(stats["connections_reused"]),
        final_connections_closed_max=optional_resource_max(stats["connections_closed"]),
        final_connections_aborted_max=optional_resource_max(stats["connections_aborted"]),
        error_types=merge_error_types(item.error_types for item in items),
        resource_coverage=resource_coverage(
            {
                "rss_mb_max": [item.peak_rss_mb for item in items],
                "threads_max": [item.peak_threads for item in items],
                "fds_max": [item.peak_fds for item in items],
                **{f"final_{key}_max": values for key, values in stats.items()},
            },
        ),
    )


def rows_with_direct_ratios(rows: list[ProxyConnectAggregateRow]) -> list[ProxyConnectAggregateRow]:
    finalized = finalize_proxy_connect_rows([asdict(row) for row in rows])
    return [
        replace(row, direct_ratio=cast("float | None", normalized["direct_ratio"]))
        for row, normalized in zip(rows, finalized, strict=True)
    ]


def client_stat_values(items: list[ProxyConnectResult], key: ClientStatKey) -> list[int | None]:
    return [item.client_stats.get(key) if item.client_stats is not None else None for item in items]


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
            "timing_scope": current_timing_scope(PROXY_CONNECT_SUITE),
            "resource_metric_schema_version": RESOURCE_METRIC_SCHEMA_VERSION,
            "args": vars(args),
            "proxy_url": redacted_proxy,
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
    markdown = render_proxy_markdown(
        load_report_template("proxy_connect_report.md.j2"),
        ProxyRenderContext(
            report=SuiteRenderContext(
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
            proxy_url=redacted_proxy,
        ),
    )
    publish_report(output_dir, timestamp, payload, markdown)


def config_order(config: str) -> int:
    order = {
        "direct": 0,
        "explicit": 1,
        "trust-env": 2,
    }
    return order.get(config, 99)
