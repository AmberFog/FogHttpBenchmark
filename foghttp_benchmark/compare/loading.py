__all__ = ("load_benchmark_report",)

from dataclasses import replace
from pathlib import Path
from typing import cast

from foghttp_benchmark.compare.models import BenchmarkReport, BenchmarkRow, BenchmarkSuite, JsonObject
from foghttp_benchmark.report_schema.decoding import load_report
from foghttp_benchmark.report_schema.fields import require_integer, require_number, require_string
from foghttp_benchmark.report_schema.identity import aggregate_identity, comparison_group
from foghttp_benchmark.report_schema.resources import resource_coverage_field
from foghttp_benchmark.validity.classification import validity_summary_from_metadata


def load_benchmark_report(path: Path) -> BenchmarkReport:
    report = load_report(path)
    metadata = report.metadata
    aggregate_rows = report.aggregate_rows
    suite = cast("BenchmarkSuite", report.suite)
    rows = [benchmark_row(suite, row) for row in aggregate_rows]
    validity = validity_summary_from_metadata(metadata, suite, aggregate_rows)
    return BenchmarkReport(
        path=path,
        suite=suite,
        timestamp=str_field(metadata, "timestamp", "-"),
        package_versions=package_versions(metadata),
        rows=rows,
        aggregate_rows=aggregate_rows,
        metadata=metadata,
        validity=validity,
        run_rows=report.run_rows,
    )


def object_field(value: JsonObject, key: str) -> JsonObject:
    field = value.get(key)
    if not isinstance(field, dict):
        return {}
    return field


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
    benchmark = builder(row) if builder is not None else request_row(row, suite=suite)
    resources = (
        object_field(object_field(row, "resources"), "client")
        if suite == "response-streaming" and row.get("profile") in {"lifecycle", "async-bytes"}
        else row
    )
    coverage = resource_coverage_field(resources)
    unavailable = {name: observation.unavailable_reasons for name, observation in coverage.items()}
    if resources is not row:
        for metric, output in (
            ("rss_bytes", "sampled_peak_rss_bytes_max"),
            ("threads", "sampled_peak_threads_max"),
            ("fds", "sampled_peak_fds_max"),
        ):
            reasons = object_field(resources, "unavailable").get(metric)
            if isinstance(reasons, list) and all(isinstance(reason, str) for reason in reasons):
                unavailable[output] = tuple(reasons)
    return replace(benchmark, resource_coverage=coverage, resource_unavailable_reasons=unavailable)


def request_row(row: JsonObject, *, suite: BenchmarkSuite = "requests") -> BenchmarkRow:
    identity = aggregate_identity(suite, row)
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    scenario = str_field(row, "scenario")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    return BenchmarkRow(
        suite=suite,
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(row, "threads_max"),
        fds=resource_int_field(row, "fds_max"),
    )


def client_creation_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("client-creation", row)
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    scenario = str_field(row, "scenario")
    client_count = int_field(row, "client_count")
    iterations = int_field(row, "iterations")
    return BenchmarkRow(
        suite="client-creation",
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "peak_rss_delta_mb_max"),
        threads=resource_int_field(row, "peak_threads_delta_max"),
        fds=resource_int_field(row, "peak_fds_delta_max"),
    )


def resource_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("resource-backpressure", row)
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
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(row, "threads_max"),
        fds=resource_int_field(row, "fds_max"),
    )


def one_upstream_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("one-upstream", row)
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    group = str_field(row, "group")
    profile = str_field(row, "profile")
    concurrency = int_field(row, "concurrency")
    return BenchmarkRow(
        suite="one-upstream",
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(row, "threads_max"),
        fds=resource_int_field(row, "fds_max"),
    )


def request_builder_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("request-builder", row)
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    group = str_field(row, "group")
    kind = str_field(row, "kind")
    profile = str_field(row, "profile")
    return BenchmarkRow(
        suite="request-builder",
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(row, "threads_max"),
        fds=resource_int_field(row, "fds_max"),
    )


def response_streaming_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("response-streaming", row)
    mode = str_field(row, "mode")
    client = str_field(row, "client")
    case = str_field(row, "case")
    read = str_field(row, "read", "bytes")
    consume = str_field(row, "consume")
    concurrency = int_field(row, "concurrency")
    request_limit = int_field(row, "request_limit")
    resources = object_field(object_field(row, "resources"), "client")
    is_lifecycle = row.get("profile") in {"lifecycle", "async-bytes"}
    lifecycle_rss = resource_float_field(resources, "sampled_peak_rss_bytes_max") if is_lifecycle else None
    return BenchmarkRow(
        suite="response-streaming",
        identity=identity,
        group=comparison_group(identity),
        label=f"{mode} / {client} / {case} / {read} / {consume} / conc={concurrency} / limit={request_limit}",
        mode=mode,
        client=client,
        scenario=case,
        primary_value=optional_float_field(row, "verified_bytes_s_median")
        if row.get("profile") == "async-bytes"
        else optional_float_field(row, "ok_streams_s_median")
        if row.get("profile") == "lifecycle"
        else float_field(row, "ok_streams_s_median"),
        p95_ms=optional_float_field(row, "p95_ms_median"),
        p99_ms=optional_float_field(row, "p99_ms_median"),
        errors_total=int_field(row, "errors_total"),
        warmup_errors_total=int_field(row, "warmup_errors_total"),
        error_rate_percent=optional_float_field(row, "error_rate_percent"),
        rss_mb=lifecycle_rss / 1024 / 1024
        if is_lifecycle and lifecycle_rss is not None
        else None
        if is_lifecycle
        else resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(resources, "sampled_peak_threads_max")
        if is_lifecycle
        else resource_int_field(row, "threads_max"),
        fds=resource_int_field(resources, "sampled_peak_fds_max")
        if is_lifecycle
        else resource_int_field(row, "fds_max"),
    )


def proxy_connect_row(row: JsonObject) -> BenchmarkRow:
    identity = aggregate_identity("proxy-connect", row)
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
        identity=identity,
        group=comparison_group(identity),
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
        rss_mb=resource_float_field(row, "rss_mb_max"),
        threads=resource_int_field(row, "threads_max"),
        fds=resource_int_field(row, "fds_max"),
    )


def str_field(row: JsonObject, key: str, default: str | None = None) -> str:
    if key not in row and default is not None:
        return default
    return require_string(row.get(key), key)


def int_field(row: JsonObject, key: str) -> int:
    return require_integer(row.get(key), key)


def optional_int_field(row: JsonObject, key: str) -> int | None:
    return None if row.get(key) is None else int_field(row, key)


def float_field(row: JsonObject, key: str) -> float:
    return require_number(row.get(key), key)


def optional_float_field(row: JsonObject, key: str) -> float | None:
    return None if row.get(key) is None else float_field(row, key)


def resource_float_field(row: JsonObject, key: str) -> float | None:
    value = row.get(key)
    return None if value is None else require_number(value, key, minimum=None)


def resource_int_field(row: JsonObject, key: str) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    if type(value) is int:
        return value
    number = require_number(value, key, minimum=None)
    if number.is_integer():
        return int(number)
    msg = f"{key} must be an integer or null"
    raise ValueError(msg)
