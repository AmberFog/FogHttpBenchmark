__all__ = ("validate_ordinary_rows",)

from foghttp_benchmark.creation.constants import (
    CREATE_FIRST_REQUEST_SCENARIO,
    MANY_CLIENTS_SCENARIO,
    REUSED_REQUEST_SCENARIO,
)
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_schema.fields import require_integer, require_number, require_object, require_string


IDENTITY_FIELDS = {
    "requests": ("scenario",),
    "compressed-response": ("scenario",),
    "client-creation": ("scenario",),
    "resource-backpressure": ("scenario",),
    "one-upstream": ("case", "group", "profile"),
    "request-builder": ("case", "group", "kind", "profile"),
    "response-streaming": ("case", "read", "consume"),
    "proxy-connect": ("case", "group", "target_scheme", "config", "lifecycle"),
}
AGGREGATE_PRIMARY_FIELDS = {
    "requests": "ok_req_s_median",
    "compressed-response": "ok_req_s_median",
    "client-creation": "ops_s_median",
    "resource-backpressure": "ok_requests_total",
    "one-upstream": "ok_req_s_median",
    "request-builder": "ops_s_median",
    "response-streaming": "ok_streams_s_median",
    "proxy-connect": "ok_req_s_median",
}
RUN_PRIMARY_FIELDS = {
    "requests": "ok_requests_per_second",
    "compressed-response": "ok_requests_per_second",
    "client-creation": "operations_per_second",
    "resource-backpressure": "ok_requests",
    "one-upstream": "ok_requests_per_second",
    "request-builder": "operations_per_second",
    "response-streaming": "ok_streams_per_second",
    "proxy-connect": "ok_requests_per_second",
}
OPERATION_SUITES = {"client-creation", "request-builder"}
IDENTITY_CHOICES = {
    "mode": {"async", "sync"},
    "read": {"bytes", "text", "lines"},
    "consume": {"all", "first-chunk", "first-line"},
    "kind": {"build", "send-prepared"},
    "target_scheme": {"http", "https"},
    "config": {"direct", "explicit", "trust-env"},
    "lifecycle": {"reused-client", "cold-client"},
}
MAX_ERROR_RATE_PERCENT = 100
SUCCESS_COUNTS = {
    "resource-backpressure": "ok_requests_total",
    "one-upstream": "ok_requests_total",
    "proxy-connect": "ok_requests_total",
    "response-streaming": "ok_streams_total",
}
NUMERIC_FIELDS = (
    "req_s_median",
    "req_s_cv_percent",
    "ops_s_cv_percent",
    "streams_s_median",
    "streams_s_cv_percent",
    "duration_ms_median",
    "duration_s_median",
    "duration_s_cv_percent",
    "mb_s_median",
    "lines_s_median",
    "p50_ms_median",
    "p95_ms_median",
    "p99_ms_median",
    "duration_s",
    "requests_per_second",
    "streams_per_second",
    "mb_per_second",
    "lines_per_second",
    "p50_ms",
    "p90_ms",
    "p95_ms",
    "p99_ms",
    "min_ms",
    "max_ms",
    "process_cpu_s",
    "pool_timeout_s",
)
NULLABLE_NUMERIC_FIELDS = (
    "first_chunk_p50_ms_median",
    "first_chunk_p95_ms_median",
    "first_chunk_p50_ms",
    "first_chunk_p95_ms",
    "close_p50_ms_median",
    "close_p95_ms_median",
    "close_p50_ms",
    "close_p95_ms",
    "baseline_ratio",
    "direct_ratio",
    "rss_mb_max",
    "peak_rss_mb",
)
COUNT_FIELDS = (
    "ok_requests_total",
    "ok_streams_total",
    "ok_requests",
    "ok_streams",
    "bytes_read_total",
    "chunks_read_total",
    "text_chars_read_total",
    "lines_read_total",
    "verified_eof_bytes_total",
    "verified_eof_chunks_total",
    "recovery_failures",
    "measured_proxy_http_requests_max",
    "measured_proxy_connect_requests_max",
    "total_proxy_http_requests_max",
    "total_proxy_connect_requests_max",
    "proxy_authorization_headers_max",
    "warmup",
)
NULLABLE_COUNT_FIELDS = (
    "threads_max",
    "fds_max",
    "peak_threads",
    "peak_fds",
    "max_buffered_response_bytes",
    "max_response_body_size",
    "peak_active_requests_max",
    "peak_pending_requests_max",
    "peak_buffered_response_bytes_max",
    "peak_active_requests",
    "peak_pending_requests",
    "peak_buffered_response_bytes",
    "final_failed_requests_max",
    "final_pool_timeouts_max",
    "final_buffered_response_bytes_max",
    "final_buffered_response_budget_rejections_max",
    "final_active_requests_max",
    "final_response_body_closed_max",
    "final_response_body_reuse_eligible_max",
    "final_response_body_aborted_max",
    "final_connections_opened_max",
    "final_connections_reused_max",
    "final_connections_closed_max",
    "final_connections_aborted_max",
    "final_idle_connections_max",
)
SIGNED_NUMERIC_FIELDS = ("peak_rss_delta_mb_max", "end_rss_delta_mb_max", "peak_rss_delta_mb", "end_rss_delta_mb")
SIGNED_COUNT_FIELDS = (
    "peak_threads_delta_max",
    "end_threads_delta_max",
    "peak_fds_delta_max",
    "end_fds_delta_max",
    "peak_threads_delta",
    "end_threads_delta",
    "peak_fds_delta",
    "end_fds_delta",
)


def validate_ordinary_rows(suite: str, aggregates: list[JsonObject], runs: list[JsonObject]) -> None:
    if suite not in IDENTITY_FIELDS:
        msg = f"Unsupported ordinary report suite: {suite!r}"
        raise ValueError(msg)
    for index, row in enumerate(aggregates):
        path = f"aggregate[{index}]"
        validate_identity(suite, row, path)
        validate_aggregate(suite, row, path)
        validate_optional_fields(row, path)
    for index, row in enumerate(runs):
        path = f"runs[{index}]"
        validate_identity(suite, row, path)
        validate_run(suite, row, path)
        validate_optional_fields(row, path)


def validate_identity(suite: str, row: JsonObject, path: str) -> None:
    for field in ("mode", "client", *IDENTITY_FIELDS[suite]):
        value = require_string(row.get(field), f"{path}.{field}")
        choices = IDENTITY_CHOICES.get(field)
        if choices is not None and value not in choices:
            msg = f"{path}.{field} must be one of {', '.join(sorted(choices))}"
            raise ValueError(msg)
    if suite in OPERATION_SUITES:
        require_integer(row.get("iterations"), f"{path}.iterations", minimum=1)
        if suite == "client-creation":
            require_integer(row.get("client_count"), f"{path}.client_count", minimum=1)
    else:
        require_integer(row.get("concurrency"), f"{path}.concurrency", minimum=1)
        require_integer(row.get("request_limit"), f"{path}.request_limit")
    if suite == "resource-backpressure":
        require_integer(row.get("max_pending_requests"), f"{path}.max_pending_requests")
        for field in ("per_origin_request_limit", "max_buffered_response_bytes"):
            if field not in row:
                msg = f"{path}.{field} is required (integer or null)"
                raise ValueError(msg)
            if row[field] is not None:
                require_integer(row[field], f"{path}.{field}")


def validate_aggregate(suite: str, row: JsonObject, path: str) -> None:
    repeats = require_integer(row.get("repeats"), f"{path}.repeats", minimum=1)
    errors = require_integer(row.get("errors_total"), f"{path}.errors_total")
    primary = AGGREGATE_PRIMARY_FIELDS[suite]
    if suite == "resource-backpressure":
        require_integer(row.get(primary), f"{path}.{primary}")
    else:
        require_number(row.get(primary), f"{path}.{primary}")
    if suite in OPERATION_SUITES:
        validate_error_bound(errors, operation_error_limit(suite, row, path) * repeats, f"{path}.errors_total")
    else:
        requests = require_integer(row.get("requests"), f"{path}.requests", minimum=1)
        require_integer(row.get("warmup_errors_total"), f"{path}.warmup_errors_total")
        validate_error_bound(errors, requests * repeats, f"{path}.errors_total")
        success_field = SUCCESS_COUNTS.get(suite)
        if success_field is not None:
            successes = require_integer(row.get(success_field), f"{path}.{success_field}")
            if successes + errors != requests * repeats:
                msg = f"{path}.{success_field} + errors_total must equal requests * repeats"
                raise ValueError(msg)
    validate_error_map(row, "error_types", "errors_total", path)
    validate_error_map(row, "warmup_error_types", "warmup_errors_total", path)


def validate_run(suite: str, row: JsonObject, path: str) -> None:
    require_integer(row.get("repeat"), f"{path}.repeat")
    require_number(row.get("duration_s"), f"{path}.duration_s")
    errors = require_integer(row.get("errors"), f"{path}.errors")
    primary = RUN_PRIMARY_FIELDS[suite]
    if suite == "resource-backpressure":
        require_integer(row.get(primary), f"{path}.{primary}")
    else:
        require_number(row.get(primary), f"{path}.{primary}")
    if suite in OPERATION_SUITES:
        limit = operation_error_limit(suite, row, path)
    else:
        limit = require_integer(row.get("requests"), f"{path}.requests", minimum=1)
        require_integer(row.get("warmup_errors"), f"{path}.warmup_errors")
        success_field = "ok_streams" if suite == "response-streaming" else "ok_requests"
        successes = require_integer(row.get(success_field), f"{path}.{success_field}")
        if successes + errors != limit:
            msg = f"{path}.{success_field} + errors must equal requests"
            raise ValueError(msg)
    validate_error_bound(errors, limit, f"{path}.errors")
    validate_error_map(row, "error_types", "errors", path)
    validate_error_map(row, "warmup_error_types", "warmup_errors", path)


def operation_error_limit(suite: str, row: JsonObject, path: str) -> int:
    iterations = require_integer(row.get("iterations"), f"{path}.iterations", minimum=1)
    if suite == "client-creation":
        scenario = row["scenario"]
        if scenario == CREATE_FIRST_REQUEST_SCENARIO:
            # A failed response check, resource snapshot and close can each record an event.
            return iterations * 3
        if scenario == REUSED_REQUEST_SCENARIO:
            # Every response check can fail before one snapshot and one cleanup failure.
            return iterations + 2
        if scenario == MANY_CLIENTS_SCENARIO:
            clients = require_integer(row.get("client_count"), f"{path}.client_count", minimum=1)
            if iterations != clients:
                msg = f"{path}.iterations must equal client_count for {MANY_CLIENTS_SCENARIO}"
                raise ValueError(msg)
            return clients + 1
    return iterations


def validate_error_bound(errors: int, limit: int, path: str) -> None:
    if errors > limit:
        msg = f"{path} must not exceed allowed error count ({limit})"
        raise ValueError(msg)


def validate_error_map(row: JsonObject, field: str, total_field: str, path: str) -> None:
    if field not in row:
        return
    errors = require_object(row[field], f"{path}.{field}")
    total = require_integer(row.get(total_field), f"{path}.{total_field}")
    count = 0
    for name, value in errors.items():
        require_string(name, f"{path}.{field} key")
        count += require_integer(value, f"{path}.{field}.{name}")
    if count != total:
        msg = f"{path}.{field} counts must sum to {total_field}"
        raise ValueError(msg)


def validate_optional_fields(row: JsonObject, path: str) -> None:
    validate_optional_numbers(row, path)
    validate_optional_counts(row, path)
    if "error_rate_percent" in row:
        error_rate = require_number(row["error_rate_percent"], f"{path}.error_rate_percent")
        if error_rate > MAX_ERROR_RATE_PERCENT:
            msg = f"{path}.error_rate_percent must be <= {MAX_ERROR_RATE_PERCENT}"
            raise ValueError(msg)
    validate_nested_counts(row, path)


def validate_optional_numbers(row: JsonObject, path: str) -> None:
    for field in NUMERIC_FIELDS:
        if field in row:
            require_number(row[field], f"{path}.{field}")
    for field in NULLABLE_NUMERIC_FIELDS:
        if field in row and row[field] is not None:
            require_number(row[field], f"{path}.{field}")
    for field in SIGNED_NUMERIC_FIELDS:
        if field in row and row[field] is not None:
            require_number(row[field], f"{path}.{field}", minimum=None)


def validate_optional_counts(row: JsonObject, path: str) -> None:
    for field in COUNT_FIELDS:
        if field in row:
            require_integer(row[field], f"{path}.{field}")
    for field in NULLABLE_COUNT_FIELDS:
        if field in row and row[field] is not None:
            require_integer(row[field], f"{path}.{field}")
    for field in SIGNED_COUNT_FIELDS:
        if field in row and row[field] is not None:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, int):
                msg = f"{path}.{field} must be an integer or null"
                raise ValueError(msg)


def validate_nested_counts(row: JsonObject, path: str) -> None:
    for field in ("client_stats", "measured_proxy", "total_proxy"):
        if field not in row or row[field] is None:
            continue
        counts = require_object(row[field], f"{path}.{field}")
        for key, value in counts.items():
            require_integer(value, f"{path}.{field}.{key}")
