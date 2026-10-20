import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.analysis import compare_reports, wins_for_report
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.rendering import load_report_template, render_compare_markdown
from tests.compare.factories import write_report as write_generic_report
from tests.streaming.attribution_report_factory import mutate_report, write_report


@pytest.mark.parametrize("profile", [None, "default", "unknown", "lifecycle"])
@pytest.mark.parametrize("row_profile", ["async-bytes", None, "default"])
def test_attribution_profile_corruption_cannot_disable_raw_validation_or_enable_rankings(
    tmp_path: Path,
    profile: str | None,
    row_profile: str | None,
) -> None:
    paths = [write_report(tmp_path / name, with_provenance=True) for name in ("old", "new")]
    for path in paths:
        payload = json.loads(path.read_text())
        if profile is None:
            del payload["metadata"]["profile"]
        else:
            payload["metadata"]["profile"] = profile
        for row in payload["aggregate"]:
            if row_profile is None:
                del row["profile"]
            else:
                row["profile"] = row_profile
        assert payload["metadata"]["validity"]["status"] == "valid"
        path.write_text(json.dumps(payload))
        for sidecar in (path.parent / "raw").iterdir():
            sidecar.unlink()

    old, new = (load_benchmark_report(path) for path in paths)
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=3)

    for report in (old, new):
        assert report.metadata.get("profile") == profile
        assert report.metadata["raw_evidence_validation"]["status"] == "invalid"
        assert report.validity.status == "invalid"
        assert not report.validity.can_compare
        assert {reason.code for reason in report.validity.reasons} >= {
            "streaming_profile_mismatch",
            "attribution_raw_evidence_invalid",
        }
        assert wins_for_report(report, "foghttp") is None
    assert comparison.validity.blocks_strong_conclusions
    assert comparison.wins is None
    assert "Competitive Position" not in render_compare_markdown(
        load_report_template("compare_report.md.j2"),
        comparison,
    )


@pytest.mark.parametrize("remove_row_profile", [False, True])
def test_missing_attribution_metadata_profile_cannot_hide_source_or_harness_changes(
    tmp_path: Path,
    *,
    remove_row_profile: bool,
) -> None:
    old_path = write_report(tmp_path / "old", with_provenance=True)
    new_path = write_report(tmp_path / "new", with_provenance=True)
    for path in (old_path, new_path):
        payload = json.loads(path.read_text())
        del payload["metadata"]["profile"]
        if remove_row_profile:
            for row in payload["aggregate"]:
                del row["profile"]
        path.write_text(json.dumps(payload))
    mutate_report(new_path, source_sha="2" * 40)
    old, new = load_benchmark_report(old_path), load_benchmark_report(new_path)

    with pytest.raises(ValueError, match="source revisions differ"):
        compare_reports(old, new, focus_client="foghttp", top_n=3)

    payload = json.loads(new_path.read_text())
    payload["metadata"]["research_provenance"]["manifest"]["harness"]["sha"] = "4" * 40
    new_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="harness identities differ"):
        compare_reports(
            old,
            load_benchmark_report(new_path),
            focus_client="foghttp",
            top_n=3,
            comparison_axis="foghttp-source",
        )


@pytest.mark.parametrize("profile", [None, "default", "unknown"])
@pytest.mark.parametrize("row_profile", ["lifecycle", None, "default"])
def test_lifecycle_profile_corruption_cannot_hide_missing_process_evidence(
    tmp_path: Path,
    profile: str | None,
    row_profile: str | None,
) -> None:
    paths = [
        write_generic_report(
            tmp_path,
            f"{name}.json",
            suite="response-streaming",
            foghttp_version="0.4.2",
            aggregate=[
                {
                    "profile": "lifecycle",
                    "mode": "async",
                    "client": "foghttp",
                    "case": "stream-1m",
                    "read": "bytes",
                    "consume": "all",
                    "concurrency": 1,
                    "request_limit": 1,
                    "requests": 20,
                    "repeats": 1,
                    "ok_streams_total": 20,
                    "errors_total": 0,
                    "warmup_errors_total": 0,
                    "configuration": {"body_bytes": 1_048_576},
                    "ok_streams_s_median": 100.0,
                },
            ],
        )
        for name in ("old", "new")
    ]
    for path in paths:
        payload = json.loads(path.read_text())
        payload["metadata"]["isolation"] = {"mode": "per-lifecycle-case"}
        payload["metadata"]["validity"] = {"status": "valid", "can_compare": True, "reasons": []}
        if profile is None:
            payload["metadata"].pop("profile", None)
        else:
            payload["metadata"]["profile"] = profile
        for row in payload["aggregate"]:
            if row_profile is None:
                del row["profile"]
            else:
                row["profile"] = row_profile
        path.write_text(json.dumps(payload))

    old, new = (load_benchmark_report(path) for path in paths)
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=3)

    assert {reason.code for reason in new.validity.reasons} >= {
        "streaming_profile_mismatch",
        "lifecycle_cases_missing",
    }
    assert comparison.validity.blocks_strong_conclusions
    assert comparison.wins is None
    assert wins_for_report(new, "foghttp") is None


def test_mixed_research_row_profiles_are_invalid_when_metadata_matches_one(tmp_path: Path) -> None:
    path = write_report(tmp_path, with_provenance=True)
    payload = json.loads(path.read_text())
    row = dict(payload["aggregate"][0])
    row["profile"] = "lifecycle"
    payload["aggregate"].append(row)
    path.write_text(json.dumps(payload))

    report = load_benchmark_report(path)

    assert not report.validity.can_compare
    assert "streaming_profile_mismatch" in {reason.code for reason in report.validity.reasons}
