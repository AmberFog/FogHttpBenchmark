__all__ = (
    "VALIDITY_STATUSES",
    "ValidityReason",
    "ValidityStatus",
    "ValiditySummary",
)

from dataclasses import dataclass
from typing import Literal, TypeAlias

from foghttp_benchmark.models import JsonObject


ValidityStatus: TypeAlias = Literal["valid", "warning", "needs-rerun", "invalid"]
VALIDITY_STATUSES: tuple[ValidityStatus, ...] = ("valid", "warning", "needs-rerun", "invalid")


@dataclass(frozen=True, slots=True)
class ValidityReason:
    status: ValidityStatus
    code: str
    message: str
    row_label: str
    row: JsonObject


@dataclass(frozen=True, slots=True)
class ValiditySummary:
    status: ValidityStatus
    is_valid: bool
    can_compare: bool
    reason_count: int
    reason_counts: dict[str, int]
    reasons: tuple[ValidityReason, ...]
