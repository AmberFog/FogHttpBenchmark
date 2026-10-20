import pytest

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.serialization import validity_summary_from_payload


@pytest.mark.parametrize("field", ["is_valid", "can_compare"])
@pytest.mark.parametrize("value", ["true", "false", 0, 1, None, []])
def test_payload_flags_require_booleans(field: str, value: object) -> None:
    payload: JsonObject = {"status": "invalid", "reasons": [], field: value}

    with pytest.raises(TypeError, match=rf"metadata\.validity\.{field} must be a boolean"):
        validity_summary_from_payload(payload)


def test_saved_compatibility_warning_cannot_enable_comparison() -> None:
    summary = validity_summary_from_payload(
        {
            "status": "warning",
            "can_compare": True,
            "reasons": [{"status": "warning", "code": "expected_compatibility_failure"}],
        },
    )

    assert summary.status == "warning"
    assert not summary.can_compare


def test_saved_status_cannot_weaken_a_blocking_reason() -> None:
    summary = validity_summary_from_payload(
        {
            "status": "valid",
            "can_compare": True,
            "reasons": [{"status": "invalid", "code": "child_process_failed"}],
        },
    )

    assert summary.status == "invalid"
    assert not summary.is_valid
    assert not summary.can_compare


def test_payload_booleans_cannot_weaken_status_gate() -> None:
    summary = validity_summary_from_payload(
        {
            "status": "needs-rerun",
            "is_valid": True,
            "can_compare": True,
            "reasons": [],
        },
    )

    assert not summary.is_valid
    assert not summary.can_compare


@pytest.mark.parametrize("status", [None, 1, True, "unknown", ""])
def test_payload_status_must_be_known(status: object) -> None:
    with pytest.raises(ValueError, match=r"metadata\.validity\.status"):
        validity_summary_from_payload({"status": status, "reasons": []})


def test_payload_requires_status() -> None:
    with pytest.raises(ValueError, match=r"metadata\.validity\.status"):
        validity_summary_from_payload({"reasons": []})


@pytest.mark.parametrize("reasons", [None, {}, "invalid", [None], [1], ["invalid"]])
def test_payload_does_not_drop_malformed_reasons(reasons: object) -> None:
    with pytest.raises(TypeError, match=r"metadata\.validity\.reasons"):
        validity_summary_from_payload({"status": "valid", "reasons": reasons})


def test_payload_requires_reasons() -> None:
    with pytest.raises(TypeError, match=r"metadata\.validity\.reasons"):
        validity_summary_from_payload({"status": "valid"})


@pytest.mark.parametrize(
    ("reason", "field"),
    [
        ({"code": "prior"}, "status"),
        ({"status": "unknown", "code": "prior"}, "status"),
        ({"status": "invalid"}, "code"),
        ({"status": "invalid", "code": 1}, "code"),
        ({"status": "invalid", "code": ""}, "code"),
        ({"status": "invalid", "code": "prior", "message": None}, "message"),
        ({"status": "invalid", "code": "prior", "row_label": []}, "row_label"),
        ({"status": "invalid", "code": "prior", "row": []}, "row"),
        ({"status": "invalid", "code": "prior", "row": {1: "x"}}, "row"),
    ],
)
def test_reason_fields_are_not_coerced(reason: JsonObject, field: str) -> None:
    with pytest.raises((TypeError, ValueError), match=rf"metadata\.validity\.reasons\[0\]\.{field}"):
        validity_summary_from_payload({"status": "valid", "reasons": [reason]})


@pytest.mark.parametrize("count", [None, True, -1, 0.0, "0", 1])
def test_reason_count_requires_exact_integer_cardinality(count: object) -> None:
    with pytest.raises(ValueError, match=r"metadata\.validity\.reason_count"):
        validity_summary_from_payload({"status": "valid", "reasons": [], "reason_count": count})


@pytest.mark.parametrize(
    "counts",
    [None, [], "", {"invalid": 1}, {"valid": True}, {"valid": -1}, {"valid": "0"}, {"valid": 0.0}, {"unknown": 0}],
)
def test_reason_counts_require_exact_integer_status_counts(counts: object) -> None:
    with pytest.raises((TypeError, ValueError), match=r"metadata\.validity\.reason_counts"):
        validity_summary_from_payload({"status": "valid", "reasons": [], "reason_counts": counts})


def test_partial_legacy_validity_derives_only_absent_fields() -> None:
    summary = validity_summary_from_payload(
        {"status": "invalid", "reasons": [{"status": "invalid", "code": "prior_host_failure"}]},
    )

    assert summary.status == "invalid"
    assert summary.can_compare is False
    assert summary.is_valid is False
    assert summary.reason_count == 1
    assert summary.reason_counts == {"invalid": 1}
    assert summary.reasons[0].message == ""
    assert summary.reasons[0].row_label == "-"
    assert summary.reasons[0].row == {}


def test_saved_comparison_restriction_without_reasons_is_preserved() -> None:
    summary = validity_summary_from_payload({"status": "valid", "reasons": [], "can_compare": False})

    assert summary.status == "valid"
    assert summary.can_compare is False
