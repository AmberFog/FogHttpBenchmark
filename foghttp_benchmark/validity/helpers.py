__all__ = (
    "CV_FIELDS",
    "HIGH_CV_WARNING_PERCENT",
    "PRIMARY_METRIC_FIELDS",
    "combined_status",
    "count_reasons",
    "dict_field",
    "first_primary_value",
    "int_field",
    "int_value",
    "ok_total_value",
    "optional_float_field",
    "row_reference",
    "str_field",
    "validity_reason",
)

from collections.abc import Iterable

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.models import VALIDITY_STATUSES, ValidityReason, ValidityStatus


HIGH_CV_WARNING_PERCENT = 50.0
STATUS_SEVERITY = {status: index for index, status in enumerate(VALIDITY_STATUSES)}
ROW_REFERENCE_FIELDS = (
    "mode",
    "client",
    "scenario",
    "case",
    "group",
    "target_scheme",
    "config",
    "lifecycle",
    "kind",
    "profile",
    "read",
    "consume",
    "concurrency",
    "request_limit",
    "client_count",
    "iterations",
)
PRIMARY_METRIC_FIELDS = (
    "ok_req_s_median",
    "ok_streams_s_median",
    "ops_s_median",
    "ok_requests_total",
)
CV_FIELDS = (
    "req_s_cv_percent",
    "streams_s_cv_percent",
    "ops_s_cv_percent",
    "duration_s_cv_percent",
)


def combined_status(statuses: Iterable[ValidityStatus]) -> ValidityStatus:
    status: ValidityStatus = "valid"
    for item in statuses:
        if STATUS_SEVERITY[item] > STATUS_SEVERITY[status]:
            status = item
    return status


def count_reasons(reasons: list[ValidityReason]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason.status] = counts.get(reason.status, 0) + 1
    return counts


def row_reference(row: JsonObject) -> JsonObject:
    return {field_name: row[field_name] for field_name in ROW_REFERENCE_FIELDS if field_name in row}


def validity_reason(
    *,
    status: ValidityStatus,
    code: str,
    message: str,
    row: JsonObject,
) -> ValidityReason:
    return ValidityReason(
        status=status,
        code=code,
        message=message,
        row_label=row_label(row),
        row=row,
    )


def row_label(row: JsonObject) -> str:
    parts = [str(row[field_name]) for field_name in ROW_REFERENCE_FIELDS if field_name in row and row[field_name] != ""]
    if not parts and "sequence" in row:
        parts = [f"child={row.get('sequence')}", str(row.get("client", "")), str(row.get("scenario", ""))]
    return " / ".join(parts) if parts else "-"


def first_primary_value(row: JsonObject) -> float | None:
    for field_name in PRIMARY_METRIC_FIELDS:
        value = optional_float_field(row, field_name)
        if value is not None:
            return value
    return None


def ok_total_value(row: JsonObject) -> int | None:
    for field_name in ("ok_requests_total", "ok_streams_total"):
        if row.get(field_name) is not None:
            return int_field(row, field_name)
    return None


def dict_field(row: JsonObject, key: str) -> dict[str, int]:
    value = row.get(key)
    if not isinstance(value, dict):
        return {}
    return {str(name): int_value(count) for name, count in value.items()}


def str_field(row: JsonObject, key: str, default: str = "") -> str:
    value = row.get(key, default)
    return value if isinstance(value, str) else str(value)


def int_field(row: JsonObject, key: str, default: int = 0) -> int:
    return int_value(row.get(key, default), default=default)


def int_value(value: object, default: int = 0) -> int:
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


def optional_float_field(row: JsonObject, key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
