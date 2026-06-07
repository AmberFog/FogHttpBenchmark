__all__ = ("validity_payload", "validity_summary_from_payload")

from typing import cast

from foghttp_benchmark.models import JsonObject
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


def validity_summary_from_payload(payload: JsonObject) -> ValiditySummary | None:
    status = status_value(payload.get("status"))
    if status is None:
        return None
    reasons = tuple(reason_from_payload(item) for item in list_field(payload.get("reasons")))
    reason_counts = reason_counts_from_payload(payload.get("reason_counts"))
    if not reason_counts:
        reason_counts = count_reasons(reasons)
    status_is_valid = status == "valid"
    status_can_compare = status in ("valid", "warning")
    return ValiditySummary(
        status=status,
        is_valid=bool_value(payload.get("is_valid"), default=status_is_valid) and status_is_valid,
        can_compare=bool_value(payload.get("can_compare"), default=status_can_compare) and status_can_compare,
        reason_count=int_value(payload.get("reason_count"), len(reasons)),
        reason_counts=reason_counts,
        reasons=reasons,
    )


def reason_from_payload(payload: JsonObject) -> ValidityReason:
    status = status_value(payload.get("status")) or "warning"
    row = payload.get("row")
    return ValidityReason(
        status=status,
        code=str(payload.get("code", "unknown")),
        message=str(payload.get("message", "")),
        row_label=str(payload.get("row_label", "-")),
        row=cast("JsonObject", row) if isinstance(row, dict) else {},
    )


def status_value(value: object) -> ValidityStatus | None:
    if isinstance(value, str) and value in VALIDITY_STATUSES:
        return value
    return None


def list_field(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [cast("JsonObject", item) for item in value if isinstance(item, dict)]


def reason_counts_from_payload(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int_value(count, 0) for key, count in value.items()}


def count_reasons(reasons: tuple[ValidityReason, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason.status] = counts.get(reason.status, 0) + 1
    return counts


def int_value(value: object, default: int) -> int:
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


def bool_value(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default
