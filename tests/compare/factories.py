__all__ = (
    "JsonObject",
    "legacy_request_row",
    "one_upstream_row",
    "request_builder_row",
    "request_row",
    "resource_row",
    "timing_request_report",
    "write_report",
)

import json
from pathlib import Path
from typing import TypeAlias

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.report_schema.decoding import report_suite
from foghttp_benchmark.validity.streaming_profiles import uses_streaming_profile


JsonObject: TypeAlias = dict[str, object]


def write_report(
    directory: Path,
    name: str,
    *,
    aggregate: list[JsonObject],
    foghttp_version: str,
    suite: str | None = None,
) -> Path:
    metadata: JsonObject = {
        "package_versions": {"foghttp": foghttp_version},
        "timestamp": "20260516-120000",
    }
    if suite is not None:
        metadata["suite"] = suite
    selected_suite = report_suite(metadata, aggregate)
    profile = "default"
    if uses_streaming_profile(metadata, aggregate, "async-bytes"):
        profile = "async-bytes"
    elif uses_streaming_profile(metadata, aggregate, "lifecycle"):
        profile = "lifecycle"
    metadata["timing_scope"] = current_timing_scope(selected_suite, profile)

    path = directory / name
    payload: JsonObject = {
        "aggregate": aggregate,
        "metadata": metadata,
        "runs": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def timing_request_report(directory: Path, name: str, scope: str | None) -> Path:
    path = write_report(
        directory,
        name,
        aggregate=[request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)],
        suite="requests",
        foghttp_version="0.4.2",
    )
    payload = json.loads(path.read_text())
    if scope is None:
        del payload["metadata"]["timing_scope"]
    else:
        payload["metadata"]["timing_scope"] = scope
    path.write_text(json.dumps(payload))
    return path


def legacy_request_row(client: str, *, ok_req_s: float, p95_ms: float) -> JsonObject:
    row = request_row(client, ok_req_s=ok_req_s, p95_ms=p95_ms)
    row["max_connections"] = row.pop("request_limit")
    return row


def request_row(client: str, *, ok_req_s: float, p95_ms: float) -> JsonObject:
    return {
        "client": client,
        "concurrency": 10,
        "error_rate_percent": 0.0,
        "errors_total": 0,
        "fds_max": 5,
        "mode": "async",
        "ok_req_s_median": ok_req_s,
        "p95_ms_median": p95_ms,
        "p99_ms_median": 3.0,
        "request_limit": 10,
        "requests": 1000,
        "repeats": 1,
        "rss_mb_max": 20.0,
        "scenario": "json-small",
        "threads_max": 2,
        "warmup_errors_total": 0,
    }


def one_upstream_row(client: str, *, ok_req_s: float, p95_ms: float) -> JsonObject:
    return {
        "case": "defaults-get",
        "client": client,
        "concurrency": 10,
        "error_rate_percent": 0.0,
        "errors_total": 0,
        "fds_max": 5,
        "group": "get",
        "mode": "async",
        "ok_req_s_median": ok_req_s,
        "p95_ms_median": p95_ms,
        "p99_ms_median": 3.0,
        "profile": "defaults",
        "request_limit": 10,
        "requests": 1000,
        "repeats": 1,
        "ok_requests_total": 1000,
        "rss_mb_max": 20.0,
        "threads_max": 2,
        "warmup_errors_total": 0,
    }


def request_builder_row(client: str, *, ops_s: float, p95_ms: float) -> JsonObject:
    return {
        "case": "default-params",
        "client": client,
        "errors_total": 0,
        "fds_max": 5,
        "group": "query",
        "iterations": 1000,
        "repeats": 1,
        "kind": "build",
        "mode": "async",
        "ops_s_median": ops_s,
        "p95_ms_median": p95_ms,
        "p99_ms_median": 0.01,
        "profile": "defaults",
        "rss_mb_max": 20.0,
        "threads_max": 2,
    }


def resource_row(*, ok_requests: int, errors: int) -> JsonObject:
    return {
        "client": "foghttp",
        "concurrency": 10,
        "error_rate_percent": errors / (ok_requests + errors) * 100,
        "errors_total": errors,
        "fds_max": 5,
        "max_buffered_response_bytes": None,
        "max_pending_requests": 10,
        "mode": "async",
        "ok_requests_total": ok_requests,
        "p95_ms_median": 5.0,
        "p99_ms_median": 8.0,
        "per_origin_request_limit": 1,
        "request_limit": 1,
        "requests": ok_requests + errors,
        "repeats": 1,
        "rss_mb_max": 25.0,
        "scenario": "active-limit-serial",
        "threads_max": 2,
        "warmup_errors_total": 0,
    }
