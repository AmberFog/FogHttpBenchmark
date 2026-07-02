__all__ = ("classify_report_validity", "validity_summary_from_metadata")

from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.children import child_process_reasons
from foghttp_benchmark.validity.generic import error_reasons, variation_reasons, zero_primary_metric_reasons
from foghttp_benchmark.validity.helpers import combined_status, count_reasons
from foghttp_benchmark.validity.models import ValidityReason, ValiditySummary
from foghttp_benchmark.validity.proxy import proxy_specific_reasons
from foghttp_benchmark.validity.resource import resource_recovery_reasons
from foghttp_benchmark.validity.serialization import validity_summary_from_payload


def validity_summary_from_metadata(
    metadata: JsonObject,
    suite: str,
    aggregate_rows: list[JsonObject],
) -> ValiditySummary:
    validity = metadata.get("validity")
    if isinstance(validity, dict):
        summary = validity_summary_from_payload(cast("JsonObject", validity))
        if summary is not None:
            return summary
    return classify_report_validity(suite=suite, aggregate_rows=aggregate_rows, metadata=metadata)


def classify_report_validity(
    *,
    suite: str,
    aggregate_rows: list[JsonObject],
    metadata: JsonObject | None = None,
) -> ValiditySummary:
    reasons = [
        *child_process_reasons(metadata or {}),
        *(reason for row in aggregate_rows for reason in row_reasons(suite, row)),
    ]
    status = combined_status(reason.status for reason in reasons)
    return ValiditySummary(
        status=status,
        is_valid=status == "valid",
        can_compare=status in ("valid", "warning"),
        reason_count=len(reasons),
        reason_counts=count_reasons(reasons),
        reasons=tuple(reasons),
    )


def row_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    reasons.extend(proxy_specific_reasons(suite, row))
    reasons.extend(error_reasons(suite, row))
    reasons.extend(zero_primary_metric_reasons(suite, row))
    reasons.extend(variation_reasons(row))
    reasons.extend(resource_recovery_reasons(suite, row))
    return reasons
