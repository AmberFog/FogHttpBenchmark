__all__ = (
    "resource_expected_pressure_row",
    "resource_recovery_reasons",
    "unexpected_error_count",
)

from foghttp_benchmark.constants import RESOURCE_BACKPRESSURE_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import (
    dict_field,
    int_field,
    int_value,
    row_reference,
    str_field,
    validity_reason,
)
from foghttp_benchmark.validity.models import ValidityReason


EXPECTED_RESOURCE_ERRORS: dict[str, frozenset[str]] = {
    "aggregate-buffered-budget": frozenset(("ResponseBodyBudgetExceededError",)),
    "pending-queue-full": frozenset(("PoolTimeout",)),
    "pool-timeout-recovery": frozenset(("PoolTimeout",)),
    "response-body-limit": frozenset(("ResponseBodyTooLargeError",)),
}


def unexpected_error_count(
    suite: str,
    row: JsonObject,
    errors_total: int,
    *,
    error_field: str = "error_types",
) -> int:
    if errors_total <= 0:
        return 0
    if suite != RESOURCE_BACKPRESSURE_SUITE:
        return errors_total
    expected_types = EXPECTED_RESOURCE_ERRORS.get(str_field(row, "scenario"), frozenset())
    error_types = dict_field(row, error_field)
    if any(count < 0 for count in error_types.values()) or sum(error_types.values()) != errors_total:
        return errors_total
    expected_total = sum(int_value(value) for key, value in error_types.items() if key in expected_types)
    return max(0, errors_total - expected_total)


def resource_expected_pressure_row(suite: str, row: JsonObject) -> bool:
    if suite != RESOURCE_BACKPRESSURE_SUITE:
        return False
    return str_field(row, "scenario") in EXPECTED_RESOURCE_ERRORS


def resource_recovery_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    if suite != RESOURCE_BACKPRESSURE_SUITE:
        return []
    failures = int_field(row, "recovery_failures")
    if failures <= 0:
        return []
    return [
        validity_reason(
            status="needs-rerun",
            code="resource_recovery_failed",
            message=f"Resource recovery health check failed in {failures} repeats.",
            row=row_reference(row),
        ),
    ]
