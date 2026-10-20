import pytest

from foghttp_benchmark.constants import REQUESTS_SUITE
from foghttp_benchmark.validity.classification import (
    classify_report_validity,
    combine_validity_summaries,
    validity_summary_from_metadata,
)
from foghttp_benchmark.validity.serialization import validity_summary_from_payload
from tests.validity.factories import compatibility_row


DISTINCT_REASON_COUNT = 2


@pytest.mark.parametrize("value", [None, [], "invalid", True])
def test_present_malformed_validity_is_not_ignored(value: object) -> None:
    with pytest.raises(TypeError, match=r"metadata\.validity must be an object"):
        validity_summary_from_metadata({"validity": value}, REQUESTS_SUITE, [compatibility_row()])


def test_unknown_recorded_status_is_not_replaced_by_current_success() -> None:
    with pytest.raises(ValueError, match=r"metadata\.validity\.status"):
        validity_summary_from_metadata(
            {"validity": {"status": "unknown", "reasons": []}},
            REQUESTS_SUITE,
            [compatibility_row()],
        )


def test_absent_legacy_validity_uses_current_classification() -> None:
    rows = [compatibility_row()]

    assert validity_summary_from_metadata({}, REQUESTS_SUITE, rows) == classify_report_validity(
        suite=REQUESTS_SUITE,
        aggregate_rows=rows,
    )


@pytest.mark.parametrize("status", ["valid", "warning", "needs-rerun", "invalid"])
def test_combining_never_improves_a_recorded_status(status: str) -> None:
    recorded = validity_summary_from_payload({"status": status, "reasons": []})
    current = classify_report_validity(suite=REQUESTS_SUITE, aggregate_rows=[compatibility_row()])

    forward = combine_validity_summaries((current, recorded))
    reverse = combine_validity_summaries((recorded, current))

    assert forward == reverse
    assert forward.status == status
    assert forward.can_compare is recorded.can_compare
    assert forward.is_valid is recorded.is_valid


def test_combining_preserves_boolean_restrictions_without_reasons() -> None:
    recorded = validity_summary_from_payload(
        {"status": "valid", "reasons": [], "can_compare": False, "is_valid": False},
    )
    current = classify_report_validity(suite=REQUESTS_SUITE, aggregate_rows=[compatibility_row()])

    merged = combine_validity_summaries((current, recorded))

    assert merged.status == "valid"
    assert merged.can_compare is False
    assert merged.is_valid is False
    assert merged.reason_count == 0


def test_combining_keeps_distinct_reasons_and_deduplicates_identical_ones() -> None:
    first = validity_summary_from_payload(
        {"status": "warning", "reasons": [{"status": "warning", "code": "prior_warning"}]},
    )
    second = validity_summary_from_payload(
        {"status": "invalid", "reasons": [{"status": "invalid", "code": "prior_failure"}]},
    )

    merged = combine_validity_summaries((first, second, first))

    assert merged.status == "invalid"
    assert merged.can_compare is False
    assert merged.reason_count == DISTINCT_REASON_COUNT
    assert merged.reason_counts == {"warning": 1, "invalid": 1}
    assert merged.reasons == (*first.reasons, *second.reasons)


def test_combining_keeps_expected_compatibility_failure_noncomparable() -> None:
    diagnostic = validity_summary_from_payload(
        {"status": "warning", "reasons": [{"status": "warning", "code": "expected_compatibility_failure"}]},
    )
    current = classify_report_validity(suite=REQUESTS_SUITE, aggregate_rows=[compatibility_row()])

    merged = combine_validity_summaries((current, diagnostic))

    assert merged.status == "warning"
    assert merged.can_compare is False
