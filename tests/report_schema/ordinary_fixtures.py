from foghttp_benchmark.models import JsonObject


ORDINARY_SUITES = (
    "requests",
    "compressed-response",
    "client-creation",
    "resource-backpressure",
    "one-upstream",
    "request-builder",
    "response-streaming",
    "proxy-connect",
)


def ordinary_aggregate(suite: str) -> JsonObject:
    row = ordinary_identity(suite)
    row.update(repeats=2, errors_total=0)
    if suite in {"client-creation", "request-builder"}:
        row.update(ops_s_median=4.0)
    else:
        row.update(requests=4, warmup_errors_total=0, error_types={}, warmup_error_types={})
        if suite == "resource-backpressure":
            row.update(ok_requests_total=8)
        elif suite == "response-streaming":
            row.update(ok_streams_s_median=4.0, ok_streams_total=8)
        else:
            row.update(ok_req_s_median=4.0)
            if suite in {"one-upstream", "proxy-connect"}:
                row.update(ok_requests_total=8)
    return row


def ordinary_run(suite: str) -> JsonObject:
    row = ordinary_identity(suite)
    row.update(repeat=0, errors=0, duration_s=1.0, error_types={})
    if suite in {"client-creation", "request-builder"}:
        row.update(operations_per_second=4.0)
    else:
        row.update(requests=4, warmup_errors=0, warmup_error_types={})
        if suite == "response-streaming":
            row.update(ok_streams=4, ok_streams_per_second=4.0)
        else:
            row.update(ok_requests=4)
            if suite != "resource-backpressure":
                row.update(ok_requests_per_second=4.0)
    return row


def ordinary_identity(suite: str) -> JsonObject:
    row: JsonObject = {"mode": "async", "client": "foghttp"}
    if suite in {"requests", "compressed-response", "client-creation", "resource-backpressure"}:
        row["scenario"] = "test-case"
    else:
        row["case"] = "test-case"
    if suite in {"client-creation", "request-builder"}:
        row["iterations"] = 4
    else:
        row.update(concurrency=1, request_limit=0)
    if suite == "client-creation":
        row["client_count"] = 1
    elif suite == "resource-backpressure":
        row.update(per_origin_request_limit=None, max_pending_requests=0, max_buffered_response_bytes=None)
    elif suite in {"one-upstream", "request-builder"}:
        row.update(group="get", profile="defaults")
        if suite == "request-builder":
            row["kind"] = "build"
    elif suite == "response-streaming":
        row.update(read="bytes", consume="all")
    elif suite == "proxy-connect":
        row.update(group="https", target_scheme="https", config="direct", lifecycle="reused-client")
    return row
