import pytest

from foghttp_benchmark.constants import REQUESTS_SUITE
from foghttp_benchmark.validity import classify_report_validity, validity_payload, validity_summary_from_metadata
from tests.validity.factories import compatibility_row


@pytest.mark.parametrize("status", ["valid", "warning"])
def test_saved_status_cannot_override_current_failures(status: str) -> None:
    summary = validity_summary_from_metadata(
        {"validity": {"status": status, "can_compare": True, "reasons": []}},
        REQUESTS_SUITE,
        [compatibility_row(errors_total=1, error_types={"RuntimeError": 1})],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert "unexpected_measured_errors" in {reason.code for reason in summary.reasons}


def test_current_classification_preserves_stored_failure() -> None:
    summary = validity_summary_from_metadata(
        {
            "validity": {
                "status": "invalid",
                "reasons": [{"status": "invalid", "code": "prior_host_failure", "row_label": "host"}],
            },
        },
        REQUESTS_SUITE,
        [compatibility_row()],
    )

    assert summary.status == "invalid"
    assert not summary.can_compare
    assert [reason.code for reason in summary.reasons] == ["prior_host_failure"]


def test_loading_does_not_duplicate_current_reasons() -> None:
    rows = [compatibility_row(warmup_errors_total=1, warmup_error_types={"RuntimeError": 1})]
    original = classify_report_validity(suite=REQUESTS_SUITE, aggregate_rows=rows)

    loaded = validity_summary_from_metadata({"validity": validity_payload(original)}, REQUESTS_SUITE, rows)

    assert loaded == original
