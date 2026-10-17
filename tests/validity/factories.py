__all__ = ("compatibility_row",)

from foghttp_benchmark.models import JsonObject


def compatibility_row(**overrides: object) -> JsonObject:
    row: JsonObject = {
        "client": "zapros-pyreqwest",
        "mode": "sync",
        "scenario": "json-small",
        "ok_req_s_median": 100.0,
        "ok_requests_total": 100,
        "errors_total": 0,
        "warmup_errors_total": 0,
        "error_types": {},
        "warmup_error_types": {},
    }
    row.update(overrides)
    return row
