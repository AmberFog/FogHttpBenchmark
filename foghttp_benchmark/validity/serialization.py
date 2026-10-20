__all__ = ("validity_payload", "validity_summary_from_payload")

from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import combined_status, count_reasons, reasons_allow_comparison
from foghttp_benchmark.validity.models import VALIDITY_STATUSES, ValidityReason, ValidityStatus, ValiditySummary


def validity_payload(summary: ValiditySummary) -> JsonObject:
    return {
        "status": summary.status,
        "is_valid": summary.is_valid,
        "can_compare": summary.can_compare,
        "reason_count": summary.reason_count,
        "reason_counts": dict(summary.reason_counts),
        "reasons": [reason_payload(reason) for reason in summary.reasons],
    }


def reason_payload(reason: ValidityReason) -> JsonObject:
    return {
        "status": reason.status,
        "code": reason.code,
        "message": reason.message,
        "row_label": reason.row_label,
        "row": dict(reason.row),
    }


def validity_summary_from_payload(payload: JsonObject) -> ValiditySummary:
    status = status_value(payload.get("status"), "metadata.validity.status")
    raw_reasons = payload.get("reasons")
    if not isinstance(raw_reasons, list):
        msg = "metadata.validity.reasons must be a list"
        raise TypeError(msg)
    reasons = tuple(reason_from_payload(item, index) for index, item in enumerate(raw_reasons))
    status = combined_status((status, *(reason.status for reason in reasons)))
    reason_counts = count_reasons(list(reasons))
    validate_reason_counts(payload, reasons, reason_counts)
    status_is_valid = status == "valid"
    status_can_compare = status in ("valid", "warning") and reasons_allow_comparison(reasons)
    return ValiditySummary(
        status=status,
        is_valid=bool_field(payload, "is_valid", default=status_is_valid) and status_is_valid,
        can_compare=bool_field(payload, "can_compare", default=status_can_compare) and status_can_compare,
        reason_count=len(reasons),
        reason_counts=reason_counts,
        reasons=reasons,
    )


def reason_from_payload(value: object, index: int) -> ValidityReason:
    path = f"metadata.validity.reasons[{index}]"
    if not isinstance(value, dict):
        msg = f"{path} must be an object"
        raise TypeError(msg)
    payload = cast("JsonObject", value)
    status = status_value(payload.get("status"), f"{path}.status")
    code = string_field(payload, "code", path)
    if not code:
        msg = f"{path}.code must be nonempty"
        raise ValueError(msg)
    row = payload.get("row", {})
    if not isinstance(row, dict) or any(not isinstance(key, str) for key in row):
        msg = f"{path}.row must be an object with string keys"
        raise ValueError(msg)
    return ValidityReason(
        status=status,
        code=code,
        message=string_field(payload, "message", path, default=""),
        row_label=string_field(payload, "row_label", path, default="-"),
        row=cast("JsonObject", row),
    )


def status_value(value: object, path: str) -> ValidityStatus:
    if isinstance(value, str) and value in VALIDITY_STATUSES:
        return value
    msg = f"{path} must be one of {', '.join(VALIDITY_STATUSES)}"
    raise ValueError(msg)


def validate_reason_counts(
    payload: JsonObject,
    reasons: tuple[ValidityReason, ...],
    expected: dict[str, int],
) -> None:
    if "reason_count" in payload:
        value = payload["reason_count"]
        if type(value) is not int or value != len(reasons):
            msg = "metadata.validity.reason_count must be an integer matching the number of reasons"
            raise ValueError(msg)
    if "reason_counts" not in payload:
        return
    counts = payload["reason_counts"]
    if not isinstance(counts, dict):
        msg = "metadata.validity.reason_counts must be an object"
        raise TypeError(msg)
    for status, count in counts.items():
        status_value(status, "metadata.validity.reason_counts key")
        if type(count) is not int or count < 0:
            msg = f"metadata.validity.reason_counts.{status} must be a nonnegative integer"
            raise ValueError(msg)
    if {status: count for status, count in counts.items() if count} != expected:
        msg = "metadata.validity.reason_counts must match the reason statuses"
        raise ValueError(msg)


def bool_field(payload: JsonObject, key: str, *, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool):
        return value
    msg = f"metadata.validity.{key} must be a boolean"
    raise TypeError(msg)


def string_field(payload: JsonObject, key: str, path: str, *, default: str | None = None) -> str:
    value = payload.get(key, default)
    if isinstance(value, str):
        return value
    msg = f"{path}.{key} must be a string"
    raise TypeError(msg)
