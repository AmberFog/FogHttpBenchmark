from copy import deepcopy
import json
from pathlib import Path
from typing import cast

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import JsonObject
from tests.report_schema.decoding_fixtures import report_payload, write_payload
from tests.report_schema.ordinary_fixtures import ordinary_aggregate, ordinary_run


def changed_measurement(suite: str, row: JsonObject) -> JsonObject:
    changed = deepcopy(row)
    if suite in {"client-creation", "request-builder"}:
        changed["ops_s_median"] = 8.0
    elif suite == "resource-backpressure":
        changed.update(ok_requests_total=7, errors_total=1, error_types={"RequestError": 1})
    elif suite == "response-streaming":
        changed["ok_streams_s_median"] = 8.0
    else:
        changed["ok_req_s_median"] = 8.0
    return changed


def saved_report(
    directory: Path,
    suite: str,
    aggregate: list[JsonObject],
    *,
    runs: list[JsonObject] | None = None,
) -> Path:
    payload = report_payload(suite)
    payload["aggregate"] = aggregate
    payload["runs"] = [] if runs is None else runs
    return write_payload(directory, payload)


def repeated_runs(suite: str) -> list[JsonObject]:
    return [{**ordinary_run(suite), "repeat": repeat} for repeat in range(2)]


def competitor_rows(suite: str) -> list[JsonObject]:
    foghttp = ordinary_aggregate(suite)
    httpx = (
        {**foghttp, "client": "httpx", "p95_ms_median": 8.0}
        if suite == "resource-backpressure"
        else changed_measurement(suite, {**foghttp, "client": "httpx"})
    )
    return [foghttp, httpx]


def multiple_case_rows(suite: str) -> list[JsonObject]:
    rows = competitor_rows(suite)
    case_field = "scenario" if "scenario" in rows[0] else "case"
    second_case = [{**row, case_field: "second-case"} for row in rows]
    return rows + second_case


def lifecycle_row() -> JsonObject:
    return {
        **ordinary_aggregate("response-streaming"),
        "profile": "lifecycle",
        "request_limit": 1,
        "configuration": {
            "body_bytes": 1024,
            "server_write_bytes": 128,
            "timeouts": {"connect": 1, "read": 2},
        },
    }


def lifecycle_report(directory: Path, rows: list[JsonObject]) -> Path:
    payload = report_payload("response-streaming")
    payload["metadata"] = {
        "suite": "response-streaming",
        "profile": "lifecycle",
        "timing_scope": current_timing_scope("response-streaming", "lifecycle"),
    }
    payload["aggregate"] = rows
    payload["runs"] = []
    return write_payload(directory, payload)


def saved_aggregate(path: Path) -> list[JsonObject]:
    payload = json.loads(path.read_text())
    return cast("list[JsonObject]", payload["aggregate"])


def replace_aggregate(path: Path, rows: list[JsonObject]) -> None:
    payload = json.loads(path.read_text())
    payload["aggregate"] = rows
    path.write_text(json.dumps(payload))
