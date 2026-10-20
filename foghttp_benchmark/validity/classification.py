__all__ = ("classify_report_validity", "combine_validity_summaries", "validity_summary_from_metadata")

from collections.abc import Iterable
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
    records: list[tuple[str, JsonObject]] = [("metadata", metadata)]
    isolation = metadata.get("isolation")
    children = isolation.get("children") if isinstance(isolation, dict) else None
    if isinstance(children, list):
        records.extend(
            (f"metadata.isolation.children[{index}]", cast("JsonObject", child))
            for index, child in enumerate(children)
            if isinstance(child, dict)
        )
    summaries = [current]
    for path, record in records:
        if "validity" in record:
            summaries.append(recorded_validity(record["validity"], path))
    return current if len(summaries) == 1 else combine_validity_summaries(summaries)


def recorded_validity(value: object, path: str) -> ValiditySummary:
    if not isinstance(value, dict):
        msg = f"{path}.validity must be an object"
        raise TypeError(msg)
    try:
        return validity_summary_from_payload(cast("JsonObject", value))
    except (TypeError, ValueError) as exc:
        if path == "metadata":
            raise
        msg = f"{path}.validity: {exc}"
        raise ValueError(msg) from exc


def combine_validity_summaries(summaries: Iterable[ValiditySummary]) -> ValiditySummary:
    """Retain every restriction when combining current, recorded or child evidence."""
    items = tuple(summaries)
    reasons: list[ValidityReason] = []
    for summary in items:
        reasons.extend(reason for reason in summary.reasons if reason not in reasons)
    status = combined_status((*(summary.status for summary in items), *(reason.status for reason in reasons)))
    return ValiditySummary(
        status=status,
        is_valid=status == "valid" and all(summary.is_valid for summary in items),
        can_compare=status in ("valid", "warning")
        and all(summary.can_compare for summary in items)
        and reasons_allow_comparison(reasons),
        reason_count=len(reasons),
        reason_counts=count_reasons(reasons),
        reasons=tuple(reasons),
    )


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
