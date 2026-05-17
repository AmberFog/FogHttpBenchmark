__all__ = (
    "JsonObject",
    "legacy_request_row",
    "request_row",
    "resource_row",
    "write_report",
)

import json
from pathlib import Path
from typing import TypeAlias


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

    path = directory / name
    payload: JsonObject = {
        "aggregate": aggregate,
        "metadata": metadata,
        "runs": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
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
        "rss_mb_max": 20.0,
        "scenario": "json-small",
        "threads_max": 2,
        "warmup_errors_total": 0,
    }


def resource_row(*, ok_requests: int, errors: int) -> JsonObject:
    return {
        "client": "foghttp",
        "concurrency": 10,
        "error_rate_percent": 0.0,
        "errors_total": errors,
        "fds_max": 5,
        "max_pending_requests": 10,
        "mode": "async",
        "ok_requests_total": ok_requests,
        "p95_ms_median": 5.0,
        "p99_ms_median": 8.0,
        "per_origin_request_limit": 1,
        "request_limit": 1,
        "rss_mb_max": 25.0,
        "scenario": "active-limit-serial",
        "threads_max": 2,
        "warmup_errors_total": 0,
    }
