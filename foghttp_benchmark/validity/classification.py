__all__ = ("classify_report_validity", "validity_summary_from_metadata")

from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.attribution import attribution_report_reasons
from foghttp_benchmark.validity.children import child_process_reasons
from foghttp_benchmark.validity.generic import error_reasons, variation_reasons, zero_primary_metric_reasons
from foghttp_benchmark.validity.helpers import combined_status, count_reasons, reasons_allow_comparison
from foghttp_benchmark.validity.lifecycle import lifecycle_report_reasons
from foghttp_benchmark.validity.models import ValidityReason, ValiditySummary
from foghttp_benchmark.validity.proxy import proxy_specific_reasons
from foghttp_benchmark.validity.resource import resource_recovery_reasons
from foghttp_benchmark.validity.serialization import validity_summary_from_payload
from foghttp_benchmark.validity.streaming_profiles import streaming_profile_reasons


def validity_summary_from_metadata(
    metadata: JsonObject,
    suite: str,
    aggregate_rows: list[JsonObject],
) -> ValiditySummary:
    current = classify_report_validity(suite=suite, aggregate_rows=aggregate_rows, metadata=metadata)
    validity = metadata.get("validity")
    if isinstance(validity, dict):
        stored = validity_summary_from_payload(cast("JsonObject", validity))
        if stored is not None:
            reasons = list(current.reasons)
            reasons.extend(reason for reason in stored.reasons if reason not in reasons)
            status = combined_status((current.status, stored.status))
            return ValiditySummary(
                status=status,
                is_valid=current.is_valid and stored.is_valid,
                can_compare=current.can_compare and stored.can_compare,
                reason_count=len(reasons),
                reason_counts=count_reasons(reasons),
                reasons=tuple(reasons),
            )
    return current


def classify_report_validity(
    *,
    suite: str,
    aggregate_rows: list[JsonObject],
    metadata: JsonObject | None = None,
) -> ValiditySummary:
    reasons = [
        *child_process_reasons(metadata or {}),
        *streaming_profile_reasons(suite, metadata or {}, aggregate_rows),
        *attribution_report_reasons(metadata or {}, aggregate_rows),
        *lifecycle_report_reasons(metadata or {}, aggregate_rows),
        *(reason for row in aggregate_rows for reason in row_reasons(suite, row)),
    ]
    status = combined_status(reason.status for reason in reasons)
    return ValiditySummary(
        status=status,
        is_valid=status == "valid",
        can_compare=reasons_allow_comparison(reasons),
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
