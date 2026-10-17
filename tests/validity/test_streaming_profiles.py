import pytest

from foghttp_benchmark.constants import REQUESTS_SUITE, RESPONSE_STREAMING_SUITE
from foghttp_benchmark.validity import classify_report_validity, validity_summary_from_metadata


@pytest.mark.parametrize(
    ("metadata_profile", "row_profiles"),
    [
        (None, ["async-bytes"]),
        (None, ["lifecycle"]),
        ("default", ["async-bytes"]),
        ("unknown", [None]),
        ({"name": "async-bytes"}, ["async-bytes"]),
        ("async-bytes", [None]),
        ("lifecycle", ["unknown"]),
        ("async-bytes", ["async-bytes", "lifecycle"]),
        ("lifecycle", ["lifecycle", None]),
    ],
)
def test_inconsistent_streaming_profiles_block_current_and_saved_validity(
    metadata_profile: object,
    row_profiles: list[object],
) -> None:
    metadata: dict[str, object] = {
        "validity": {"status": "valid", "is_valid": True, "can_compare": True, "reasons": []},
    }
    if metadata_profile is not None:
        metadata["profile"] = metadata_profile
    rows = [{"profile": profile, "ok_streams_s_median": 100.0} for profile in row_profiles]

    for summary in (
        classify_report_validity(suite=RESPONSE_STREAMING_SUITE, aggregate_rows=rows, metadata=metadata),
        validity_summary_from_metadata(metadata, RESPONSE_STREAMING_SUITE, rows),
    ):
        assert summary.status == "invalid"
        assert not summary.can_compare
        assert "streaming_profile_mismatch" in {reason.code for reason in summary.reasons}


@pytest.mark.parametrize("profile", [None, "default"])
def test_ordinary_legacy_streaming_profiles_remain_readable(profile: str | None) -> None:
    metadata: dict[str, object] = {} if profile is None else {"profile": profile}
    rows: list[dict[str, object]] = [{"ok_streams_s_median": 100.0}]

    summary = classify_report_validity(suite=RESPONSE_STREAMING_SUITE, aggregate_rows=rows, metadata=metadata)

    assert summary.status == "valid"
    assert summary.can_compare


def test_other_suites_keep_their_own_profile_names() -> None:
    summary = classify_report_validity(
        suite=REQUESTS_SUITE,
        aggregate_rows=[{"profile": "defaults", "ok_req_s_median": 100.0}],
        metadata={"profile": "defaults"},
    )

    assert summary.status == "valid"
    assert summary.can_compare


@pytest.mark.parametrize(
    "metadata",
    [
        {"policy_version": "async-bytes-v2"},
        {"config": {"attribution": {}}},
        {"conditions": {"configuration": {"attribution": {}}}},
        {"raw_evidence": []},
        {"raw_evidence_validation": {"status": "ok"}},
        {"lifecycle": {}},
        {"isolation": {"mode": "per-lifecycle-case"}},
    ],
)
def test_research_envelope_without_either_profile_is_not_an_ordinary_report(metadata: dict[str, object]) -> None:
    summary = classify_report_validity(
        suite=RESPONSE_STREAMING_SUITE,
        aggregate_rows=[{"ok_streams_s_median": 100.0}],
        metadata=metadata,
    )

    assert summary.status == "invalid"
    assert not summary.can_compare
    assert "streaming_profile_mismatch" in {reason.code for reason in summary.reasons}
