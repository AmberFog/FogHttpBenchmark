from foghttp_benchmark.validity.serialization import validity_summary_from_payload


def test_payload_bool_strings_do_not_override_status_defaults() -> None:
    summary = validity_summary_from_payload(
        {
            "status": "invalid",
            "is_valid": "true",
            "can_compare": "true",
            "reasons": [],
        },
    )

    assert summary is not None
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

    assert summary is not None
    assert not summary.is_valid
    assert not summary.can_compare
