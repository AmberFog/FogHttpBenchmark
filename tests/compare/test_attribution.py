import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from tests.streaming.attribution_report_factory import mutate_report, write_report


def test_equal_attribution_conditions_compare_without_competitive_rankings(tmp_path: Path) -> None:
    old = load_benchmark_report(write_report(tmp_path / "old", with_provenance=True))
    new = load_benchmark_report(write_report(tmp_path / "new", with_provenance=True))
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=3)
    assert comparison.overall.rows == 1
    assert comparison.overall.primary_median_ratio == 1
    assert comparison.validity.blocks_strong_conclusions is False
    assert comparison.wins is None


def test_source_revision_difference_requires_explicit_comparison_axis(tmp_path: Path) -> None:
    old = load_benchmark_report(write_report(tmp_path / "old", with_provenance=True))
    new_path = write_report(tmp_path / "new", with_provenance=True)
    mutate_report(new_path, source_sha="2" * 40)
    new = load_benchmark_report(new_path)
    with pytest.raises(ValueError, match="source revisions differ"):
        compare_reports(old, new, focus_client="foghttp", top_n=3)
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=3, comparison_axis="foghttp-source")
    assert comparison.metadata.comparison_axis == "foghttp-source"


def test_changed_conditions_and_missing_primary_do_not_silently_compare(tmp_path: Path) -> None:
    old = load_benchmark_report(write_report(tmp_path / "old", with_provenance=True))
    new_path = write_report(tmp_path / "new", with_provenance=True)
    mutate_report(new_path, condition="read-policy")
    with pytest.raises(ValueError, match="No comparable rows"):
        compare_reports(old, load_benchmark_report(new_path), focus_client="foghttp", top_n=3)
    payload = json.loads(new_path.read_text())
    del payload["aggregate"][0]["verified_bytes_s_median"]
    new_path.write_text(json.dumps(payload))
    report = load_benchmark_report(new_path)
    assert report.rows[0].primary_value is None
    assert report.validity.can_compare is False


@pytest.mark.parametrize("field", ["sha", "diff_sha256", "files_sha256"])
@pytest.mark.parametrize("axis", [None, "foghttp-source"])
def test_harness_changes_cannot_be_hidden_by_the_foghttp_source_axis(
    tmp_path: Path,
    field: str,
    axis: str | None,
) -> None:
    old = load_benchmark_report(write_report(tmp_path / "old", with_provenance=True))
    new_path = write_report(tmp_path / "new", with_provenance=True)
    payload = json.loads(new_path.read_text())
    harness = payload["metadata"]["research_provenance"]["manifest"]["harness"]
    harness[field] = {"foghttp_benchmark/cli.py": "f" * 64} if field == "files_sha256" else "f" * len(harness[field])
    new_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="harness identities differ"):
        compare_reports(old, load_benchmark_report(new_path), focus_client="foghttp", top_n=3, comparison_axis=axis)


def test_harness_checkout_path_and_branch_are_not_measurement_axes(tmp_path: Path) -> None:
    old = load_benchmark_report(write_report(tmp_path / "old", with_provenance=True))
    new_path = write_report(tmp_path / "new", with_provenance=True)
    payload = json.loads(new_path.read_text())
    payload["metadata"]["research_provenance"]["manifest"]["harness"].update(root="/different/path", branch="candidate")
    new_path.write_text(json.dumps(payload))
    result = compare_reports(old, load_benchmark_report(new_path), focus_client="foghttp", top_n=3)
    assert result.overall.rows == 1


@pytest.mark.parametrize("field", ["sha", "diff_sha256", "files_sha256"])
def test_missing_harness_evidence_blocks_strong_validity(tmp_path: Path, field: str) -> None:
    path = write_report(tmp_path, with_provenance=True)
    payload = json.loads(path.read_text())
    del payload["metadata"]["research_provenance"]["manifest"]["harness"][field]
    path.write_text(json.dumps(payload))
    report = load_benchmark_report(path)
    assert report.validity.can_compare is False
    assert "attribution_harness_provenance_missing" in {reason.code for reason in report.validity.reasons}
