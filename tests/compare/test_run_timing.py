from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.reports import build_comparison
from tests.resource_metrics.cases import RESOURCE_REPORT_CASES, ResourceReportCase
from tests.resource_metrics.report_actions import remove_resource_coverage, report_payload, write_resource_case


@pytest.mark.parametrize("case", RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize("mutation", ["different-scope", "unknown-scope", "partially-declared"])
def test_comparison_checks_every_recorded_run_before_ratios(
    tmp_path: Path,
    case: ResourceReportCase,
    side: str,
    mutation: str,
) -> None:
    original_path = write_resource_case(case, tmp_path / "original", [1, 2])
    original = remove_resource_coverage(original_path)
    payload = deepcopy(original)
    scope = payload["metadata"]["timing_scope"]
    for run in payload["runs"]:
        run["timing_scope"] = scope
    if mutation == "partially-declared":
        del payload["runs"][0]["timing_scope"]
    else:
        payload["runs"][0]["timing_scope"] = (
            "future-timing-v99"
            if mutation == "unknown-scope"
            else "requests-load-only-v2"
            if case.suite == "response-streaming"
            else "legacy-sampler-v1"
        )
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(payload))

    baseline = load_benchmark_report(original_path)
    with pytest.raises(ValueError, match="Report rows disagree on timing scope"):
        load_benchmark_report(changed_path)
    inspected = replace(baseline, path=changed_path, run_rows=payload["runs"])

    assert inspected.metadata == baseline.metadata
    assert inspected.aggregate_rows == baseline.aggregate_rows
    assert inspected.validity == baseline.validity
    assert inspected.run_rows == payload["runs"]
    old, new = (inspected, baseline) if side == "old" else (baseline, inspected)
    with pytest.raises(ValueError, match="Report rows disagree on timing scope"):
        compare_reports(old, new, focus_client="foghttp", top_n=1)


@pytest.mark.parametrize("case", RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def test_consistent_current_run_scopes_allow_comparison(tmp_path: Path, case: ResourceReportCase) -> None:
    path = write_resource_case(case, tmp_path, [1, 2])
    payload = report_payload(path)
    for run in payload["runs"]:
        run["timing_scope"] = payload["metadata"]["timing_scope"]
    path.write_text(json.dumps(payload))

    comparison = build_comparison(path, path, focus_client="foghttp", top_n=1)

    assert comparison.overall.rows == 1
    assert comparison.overall.primary_median_ratio == 1


def test_streaming_writer_report_with_only_one_conflicting_run_cannot_compare(tmp_path: Path) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == "response-streaming")
    original_path = write_resource_case(case, tmp_path / "original", [1, 2])
    original = report_payload(original_path)
    payload = deepcopy(original)
    payload["runs"][0]["timing_scope"] = "legacy-sampler-v1"
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(payload))

    baseline = load_benchmark_report(original_path)

    assert baseline.validity.status == "valid"
    assert payload["metadata"] == original["metadata"]
    assert payload["aggregate"] == original["aggregate"]
    assert payload["runs"][1:] == original["runs"][1:]
    assert payload["runs"][0] == {**original["runs"][0], "timing_scope": "legacy-sampler-v1"}
    with pytest.raises(ValueError, match=r"timing scope|resource_coverage"):
        build_comparison(original_path, changed_path, focus_client="foghttp", top_n=1)


@pytest.mark.parametrize(
    ("suite", "scope"),
    [
        ("requests", "requests-sampler-inclusive-v1"),
        ("compressed-response", "requests-sampler-inclusive-v1"),
        ("one-upstream", "one-upstream-sampler-inclusive-v1"),
        ("proxy-connect", "proxy-connect-sampler-inclusive-v1"),
        ("resource-backpressure", "resource-backpressure-sampler-inclusive-v1"),
        ("response-streaming", "legacy-sampler-v1"),
    ],
)
def test_consistent_explicit_legacy_run_scopes_allow_comparison(tmp_path: Path, suite: str, scope: str) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == suite)
    path = write_resource_case(case, tmp_path, [1, 2])
    payload = report_payload(path)
    payload["metadata"]["timing_scope"] = scope
    if "timing_scopes" in payload["metadata"]:
        payload["metadata"]["timing_scopes"] = [scope]
    for row in [*payload["aggregate"], *payload["runs"]]:
        row["timing_scope"] = scope
    path.write_text(json.dumps(payload))

    comparison = build_comparison(path, path, focus_client="foghttp", top_n=1)

    assert comparison.overall.rows == 1
    assert comparison.overall.primary_median_ratio == 1


@pytest.mark.parametrize("case", RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def test_metadata_scope_remains_sufficient_when_all_run_scopes_are_unrecorded(
    tmp_path: Path,
    case: ResourceReportCase,
) -> None:
    path = write_resource_case(case, tmp_path, [1, 2])
    payload = remove_resource_coverage(path)
    for run in payload["runs"]:
        run.pop("timing_scope", None)
    path.write_text(json.dumps(payload))

    loaded = load_benchmark_report(path)
    comparison = build_comparison(path, path, focus_client="foghttp", top_n=1)

    assert loaded.run_rows == payload["runs"]
    assert all("timing_scope" not in run for run in loaded.run_rows)
    assert comparison.overall.primary_median_ratio == 1


@pytest.mark.parametrize("case", RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def test_unlabelled_reports_stay_inspectable_without_implied_current_scope(
    tmp_path: Path,
    case: ResourceReportCase,
) -> None:
    path = write_resource_case(case, tmp_path, [1, 2])
    payload = report_payload(path)
    payload["metadata"].pop("timing_scope")
    payload["metadata"].pop("timing_scopes", None)
    for row in [*payload["aggregate"], *payload["runs"]]:
        row.pop("timing_scope", None)
    path.write_text(json.dumps(payload))

    inspected = load_benchmark_report(path)

    assert inspected.run_rows == payload["runs"]
    assert inspected.rows
    assert "timing_scope" not in inspected.metadata
    with pytest.raises(ValueError, match="Unknown or unsupported timing scope"):
        build_comparison(path, path, focus_client="foghttp", top_n=1)
