__all__ = ("ordinary_resource_row",)

from foghttp_benchmark.compare.models import BenchmarkSuite, JsonObject


def ordinary_resource_row(suite: BenchmarkSuite, value: float | None) -> JsonObject:
    row: JsonObject = {
        "mode": "async",
        "client": "foghttp",
        "repeats": 3,
        "errors_total": 0,
        "p95_ms_median": 1.0,
        "p99_ms_median": 2.0,
        "error_rate_percent": 0.0,
    }
    if suite in {"client-creation", "request-builder"}:
        row.update(iterations=100, ops_s_median=10.0)
        if suite == "client-creation":
            row.update(scenario="create-close", client_count=1)
        else:
            row.update(case="default-params", group="query", kind="build", profile="defaults")
    else:
        row.update(concurrency=1, request_limit=1, requests=10, warmup_errors_total=0)
        if suite == "response-streaming":
            row.update(case="stream-1m", read="bytes", consume="all", ok_streams_s_median=10.0, ok_streams_total=30)
        elif suite == "resource-backpressure":
            row.update(
                scenario="active-limit-serial",
                max_buffered_response_bytes=None,
                max_pending_requests=1,
                per_origin_request_limit=None,
                ok_requests_total=30,
            )
        elif suite == "proxy-connect":
            row.update(
                case="direct-https",
                group="https",
                target_scheme="https",
                config="direct",
                lifecycle="reused-client",
                ok_req_s_median=10.0,
                ok_requests_total=30,
            )
        elif suite == "one-upstream":
            row.update(case="defaults-get", group="get", profile="defaults", ok_req_s_median=10.0, ok_requests_total=30)
        else:
            row.update(scenario="gzip-64k" if suite == "compressed-response" else "json-small", ok_req_s_median=10.0)
    fields = (
        ("peak_rss_delta_mb_max", "peak_threads_delta_max", "peak_fds_delta_max")
        if suite == "client-creation"
        else ("rss_mb_max", "threads_max", "fds_max")
    )
    for metric in fields:
        row[metric] = value
    return row
