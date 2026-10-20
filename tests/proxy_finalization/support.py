from dataclasses import asdict

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.proxy_connect.finalization import finalize_proxy_connect_rows
from foghttp_benchmark.proxy_connect.models import ProxyConnectAggregateRow
from foghttp_benchmark.proxy_connect.reports import rows_with_direct_ratios


def aggregate_row(
    *,
    case: str = "direct-https",
    config: str = "direct",
    lifecycle: str = "reused-client",
    throughput: float = 100.0,
) -> ProxyConnectAggregateRow:
    return ProxyConnectAggregateRow(
        mode="async",
        client="foghttp",
        case=case,
        group="https",
        target_scheme="https",
        config=config,
        lifecycle=lifecycle,
        concurrency=10,
        request_limit=10,
        requests=100,
        repeats=3,
        ok_requests_total=300,
        errors_total=0,
        warmup_errors_total=0,
        error_rate_percent=0.0,
        ok_req_s_median=throughput,
        req_s_median=throughput,
        req_s_cv_percent=1.0,
        direct_ratio=-1.0,
        p50_ms_median=1.0,
        p95_ms_median=2.0,
        p99_ms_median=3.0,
        rss_mb_max=None,
        threads_max=None,
        fds_max=None,
        measured_proxy_http_requests_max=0,
        measured_proxy_connect_requests_max=1,
        total_proxy_http_requests_max=0,
        total_proxy_connect_requests_max=1,
        proxy_authorization_headers_max=0,
        final_connections_opened_max=None,
        final_connections_reused_max=None,
        final_connections_closed_max=None,
        final_connections_aborted_max=None,
        error_types={},
        resource_coverage={},
    )


def finalize_json(rows: list[ProxyConnectAggregateRow]) -> list[JsonObject]:
    return finalize_proxy_connect_rows([asdict(row) for row in rows])


def finalize_typed(rows: list[ProxyConnectAggregateRow]) -> list[JsonObject]:
    return [asdict(row) for row in rows_with_direct_ratios(rows)]
