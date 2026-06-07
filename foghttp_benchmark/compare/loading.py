__all__ = ("load_benchmark_report",)

import json
from pathlib import Path

from foghttp_benchmark.compare.models import BenchmarkReport, BenchmarkRow, BenchmarkSuite, JsonObject


def load_benchmark_report(path: Path) -> BenchmarkReport:
    payload = load_json_object(path)
    metadata = object_field(payload, "metadata")
    aggregate_rows = object_list_field(payload, "aggregate")
    suite = report_suite(metadata, aggregate_rows)
    rows = [benchmark_row(suite, row) for row in aggregate_rows]
    return BenchmarkReport(
        path=path,
        suite=suite,
        timestamp=str_field(metadata, "timestamp", "-"),
        package_versions=package_versions(metadata),
        rows=rows,
        aggregate_rows=aggregate_rows,
        metadata=metadata,
    )


def load_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        msg = f"{path} must contain a JSON object"
        raise TypeError(msg)
    return value


def object_field(value: JsonObject, key: str) -> JsonObject:
    field = value.get(key)
    if not isinstance(field, dict):
        return {}
    return field


def object_list_field(value: JsonObject, key: str) -> list[JsonObject]:
    field = value.get(key)
    if not isinstance(field, list):
        msg = f"JSON field {key!r} must be a list"
        raise TypeError(msg)
    rows: list[JsonObject] = []
    for item in field:
        if not isinstance(item, dict):
            msg = f"JSON field {key!r} must contain objects"
            raise TypeError(msg)
        rows.append(item)
    return rows


def report_suite(metadata: JsonObject, aggregate_rows: list[JsonObject]) -> BenchmarkSuite:
    suite = metadata.get("suite")
    known_suites: dict[str, BenchmarkSuite] = {
        "requests": "requests",
        "client-creation": "client-creation",
        "resource-backpressure": "resource-backpressure",
        "one-upstream": "one-upstream",
        "request-builder": "request-builder",
        "compressed-response": "compressed-response",
        "response-streaming": "response-streaming",
        "proxy-connect": "proxy-connect",
    }
    if isinstance(suite, str) and suite in known_suites:
        inferred_suite = known_suites[suite]
    else:
        inferred_suite = infer_suite_from_rows(aggregate_rows)
    return inferred_suite


def infer_suite_from_rows(aggregate_rows: list[JsonObject]) -> BenchmarkSuite:
    first = aggregate_rows[0] if aggregate_rows else {}
    if "kind" in first and "profile" in first and "ops_s_median" in first:
        suite: BenchmarkSuite = "request-builder"
    elif "streams_s_median" in first:
        suite = "response-streaming"
    elif "ops_s_median" in first:
        suite = "client-creation"
    elif "max_pending_requests" in first:
        suite = "resource-backpressure"
    elif "target_scheme" in first and "config" in first and "case" in first:
        suite = "proxy-connect"
    elif "profile" in first and "case" in first:
        suite = "one-upstream"
    elif "ok_req_s_median" in first:
        suite = "requests"
    else:
        suite = "unknown"
    return suite


def package_versions(metadata: JsonObject) -> dict[str, str]:
    versions = metadata.get("package_versions")
    if not isinstance(versions, dict):
        return {}
    return {str(name): str(version) for name, version in versions.items()}


def benchmark_row(suite: BenchmarkSuite, row: JsonObject) -> BenchmarkRow:
    row_builders = {
        "client-creation": client_creation_row,
        "resource-backpressure": resource_row,
        "one-upstream": one_upstream_row,
        "request-builder": request_builder_row,
        "response-streaming": response_streaming_row,
        "proxy-connect": proxy_connect_row,
    }
    builder = row_builders.get(suite)
    if builder is not None:
        return builder(row)
    return request_row(row, suite=suite)


def request_row(row: JsonObject, *, suite: BenchmarkSuite = "requests") -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    scenario = str_field(row, "scenario")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit", int_field(row, "max_connections"))
    return BenchmarkRow(
        suite=suite,
        identity=(mode, client, scenario, str(concurrency), str(request_limit)),
        group=(mode, scenario, str(concurrency), str(request_limit)),
        label=f"{mode} / {client} / {scenario} / conc={concurrency} / limit={request_limit}",
        mode=mode,
        client=client,
        scenario=scenario,
        primary_value=float_field(row, "ok_req_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def client_creation_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    scenario = str_field(row, "scenario")
    client_count = int_field(row, "client_count")
    iterations = int_field(row, "iterations")
    return BenchmarkRow(
        suite="client-creation",
        identity=(mode, client, scenario, str(client_count), str(iterations)),
        group=(mode, scenario, str(client_count), str(iterations)),
        label=f"{mode} / {client} / {scenario} / clients={client_count} / iters={iterations}",
        mode=mode,
        client=client,
        scenario=scenario,
        primary_value=float_field(row, "ops_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=0,
        error_rate_percent=None,
        rss_mb=optional_float_field(row, "peak_rss_delta_mb_max"),
        threads=optional_int_field(row, "peak_threads_delta_max"),
        fds=optional_int_field(row, "peak_fds_delta_max"),
    )


def resource_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client", "foghttp")
    scenario = str_field(row, "scenario")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    origin_limit = optional_int_field(row, "per_origin_request_limit")
    pending_limit = int_field(row, "max_pending_requests")
    origin_label = "-" if origin_limit is None else str(origin_limit)
    return BenchmarkRow(
        suite="resource-backpressure",
        identity=(mode, client, scenario, str(concurrency), str(request_limit), origin_label, str(pending_limit)),
        group=(mode, scenario, str(concurrency), str(request_limit), origin_label, str(pending_limit)),
        label=(
            f"{mode} / {client} / {scenario} / conc={concurrency} / active={request_limit} "
            f"/ origin={origin_label} / pending={pending_limit}"
        ),
        mode=mode,
        client=client,
        scenario=scenario,
        primary_value=float_field(row, "ok_requests_total"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def one_upstream_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    group = str_field(row, "group")
    profile = str_field(row, "profile")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    return BenchmarkRow(
        suite="one-upstream",
        identity=(mode, client, group, case, str(concurrency), str(request_limit)),
        group=(mode, group, case, str(concurrency), str(request_limit)),
        label=f"{mode} / {client} / {group} / {case} / {profile} / conc={concurrency}",
        mode=mode,
        client=client,
        scenario=case,
        primary_value=float_field(row, "ok_req_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def request_builder_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    group = str_field(row, "group")
    kind = str_field(row, "kind")
    profile = str_field(row, "profile")
    iterations = int_field(row, "iterations")
    return BenchmarkRow(
        suite="request-builder",
        identity=(mode, client, kind, group, case, str(iterations)),
        group=(mode, kind, group, case, str(iterations)),
        label=f"{mode} / {client} / {kind} / {group} / {case} / {profile}",
        mode=mode,
        client=client,
        scenario=case,
        primary_value=float_field(row, "ops_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=0,
        error_rate_percent=None,
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def response_streaming_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    read = str_field(row, "read", "bytes")
    consume = str_field(row, "consume")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    return BenchmarkRow(
        suite="response-streaming",
        identity=(mode, client, case, read, consume, str(concurrency), str(request_limit)),
        group=(mode, case, read, consume, str(concurrency), str(request_limit)),
        label=f"{mode} / {client} / {case} / {read} / {consume} / conc={concurrency} / limit={request_limit}",
        mode=mode,
        client=client,
        scenario=case,
        primary_value=float_field(row, "ok_streams_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def proxy_connect_row(row: JsonObject) -> BenchmarkRow:
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    target_scheme = str_field(row, "target_scheme")
    config = str_field(row, "config")
    lifecycle = str_field(row, "lifecycle")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    return BenchmarkRow(
        suite="proxy-connect",
        identity=(mode, client, case, target_scheme, config, lifecycle, str(concurrency), str(request_limit)),
        group=(mode, case, target_scheme, config, lifecycle, str(concurrency), str(request_limit)),
        label=(
            f"{mode} / {client} / {case} / {target_scheme} / {config} / {lifecycle} "
            f"/ conc={concurrency} / limit={request_limit}"
        ),
        mode=mode,
        client=client,
        scenario=case,
        primary_value=float_field(row, "ok_req_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=optional_float_field(row, "rss_mb_max"),
        threads=optional_int_field(row, "threads_max"),
        fds=optional_int_field(row, "fds_max"),
    )


def str_field(row: JsonObject, key: str, default: str = "") -> str:
    value = row.get(key, default)
    return value if isinstance(value, str) else str(value)


def int_field(row: JsonObject, key: str, default: int = 0) -> int:
    value = row.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def optional_int_field(row: JsonObject, key: str) -> int | None:
    if row.get(key) is None:
        return None
    return int_field(row, key)


def float_field(row: JsonObject, key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def optional_float_field(row: JsonObject, key: str) -> float | None:
    if row.get(key) is None:
        return None
    return float_field(row, key)
