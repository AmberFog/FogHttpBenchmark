__all__ = ("error_reasons", "variation_reasons", "zero_primary_metric_reasons")

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import (
    CV_FIELDS,
    HIGH_CV_WARNING_PERCENT,
    first_primary_value,
    int_field,
    ok_total_value,
    optional_float_field,
    row_reference,
    validity_reason,
)
from foghttp_benchmark.validity.models import ValidityReason
from foghttp_benchmark.validity.proxy import has_proxy_bypass_errors
from foghttp_benchmark.validity.resource import resource_expected_pressure_row, unexpected_error_count


def error_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    errors_total = int_field(row, "errors_total")
    warmup_errors_total = int_field(row, "warmup_errors_total")
    unexpected_errors = unexpected_error_count(suite, row, errors_total)
    if unexpected_errors > 0 and not has_proxy_bypass_errors(row):
        reasons.append(
            validity_reason(
                status="needs-rerun",
                code="unexpected_measured_errors",
                message=f"Measured run recorded {unexpected_errors} unexpected errors.",
                row=row_reference(row),
            ),
        )
    if warmup_errors_total > 0 and not resource_expected_pressure_row(suite, row):
        reasons.append(
            validity_reason(
                status="needs-rerun",
                code="unexpected_warmup_errors",
                message=f"Warmup recorded {warmup_errors_total} unexpected errors.",
                row=row_reference(row),
            ),
        )
    return reasons


def zero_primary_metric_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    if resource_expected_pressure_row(suite, row):
        return []
    primary_value = first_primary_value(row)
    if primary_value is None or primary_value > 0:
        return []
    errors_total = int_field(row, "errors_total")
    ok_total = ok_total_value(row)
    if errors_total <= 0 and ok_total is None:
        return []
    return [
        validity_reason(
            status="needs-rerun",
            code="zero_success_throughput",
            message="Primary success throughput is zero for a measured row.",
            row=row_reference(row),
        ),
    ]


def variation_reasons(row: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    for field_name in CV_FIELDS:
        value = optional_float_field(row, field_name)
        if value is None or value <= HIGH_CV_WARNING_PERCENT:
            continue
        reasons.append(
            validity_reason(
                status="warning",
                code="high_variation",
                message=f"{field_name} is {value:.1f}%, above {HIGH_CV_WARNING_PERCENT:.1f}%.",
                row=row_reference(row),
            ),
        )
    return reasons
