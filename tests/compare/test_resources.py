from dataclasses import asdict
import json
from pathlib import Path
import re

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.models import BenchmarkSuite
from foghttp_benchmark.compare.reports import build_comparison
from foghttp_benchmark.rendering import load_report_template, render_compare_markdown
from tests.compare.factories import write_report
from tests.compare.resource_factories import ordinary_resource_row


ORDINARY_SUITES: tuple[BenchmarkSuite, ...] = (
    "requests",
    "client-creation",
    "resource-backpressure",
    "one-upstream",
    "request-builder",
    "compressed-response",
    "response-streaming",
    "proxy-connect",
)
RESOURCE_FIELDS = ("rss_mb_max", "threads_max", "fds_max")
EXPECTED_REPETITIONS = 3
OBSERVED_PEAK = 10
MATCHED_ROWS = 2
EXACT_INTEGER_COUNT = 2**60 + 1


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_resource_null_zero_and_coverage_survive_comparison(tmp_path: Path, suite: BenchmarkSuite) -> None:
    old_row = ordinary_resource_row(suite, None)
    new_row = ordinary_resource_row(suite, 0)
    fields = (
        ("peak_rss_delta_mb_max", "peak_threads_delta_max", "peak_fds_delta_max")
        if suite == "client-creation"
        else RESOURCE_FIELDS
    )
    old_row["resource_coverage"] = {
        metric: {"available": 0, "expected": 3, "unavailable_reasons": ["permission denied"]} for metric in fields
    }
    new_row["resource_coverage"] = {
        metric: {"available": 3, "expected": 3, "unavailable_reasons": []} for metric in fields
    }
    old = write_report(tmp_path, "old.json", aggregate=[old_row], suite=suite, foghttp_version="0.4.2")
    new = write_report(tmp_path, "new.json", aggregate=[new_row], suite=suite, foghttp_version="0.4.2")

    comparison = build_comparison(old, new, focus_client="foghttp", top_n=1)
    assert comparison.resource_summary.old_rss_mb_max is None
    assert comparison.resource_summary.old_threads_max is None
    assert comparison.resource_summary.old_fds_max is None
    assert comparison.resource_summary.new_rss_mb_max == 0.0
    assert comparison.resource_summary.new_threads_max == 0
    assert comparison.resource_summary.new_fds_max == 0
    assert comparison.resource_coverage[0].old[fields[0]].available == 0
    assert comparison.resource_coverage[0].new[fields[0]].expected == EXPECTED_REPETITIONS
    serialized = json.loads(json.dumps(asdict(comparison), default=str))
    assert serialized["resource_summary"]["old_rss_mb_max"] is None
    assert serialized["resource_coverage"][0]["old"][fields[0]]["unavailable_reasons"] == ["permission denied"]
    markdown = render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)
    assert "| max RSS MB | unavailable | 0.0 |" in markdown
    assert "0/3 (unavailable)" in markdown
    assert "3/3" in markdown
    assert "permission denied" in markdown


def test_partial_coverage_keeps_observed_peak_and_does_not_depend_on_top_n(tmp_path: Path) -> None:
    first = ordinary_resource_row("requests", 10)
    first["resource_coverage"] = {
        "rss_mb_max": {"available": 1, "expected": 3, "unavailable_reasons": ["reason-not-recorded"]},
    }
    second = {**first, "scenario": "second-case"}
    old = write_report(tmp_path, "old.json", aggregate=[first, second], suite="requests", foghttp_version="0.4.2")
    new = write_report(tmp_path, "new.json", aggregate=[first, second], suite="requests", foghttp_version="0.4.2")

    comparison = build_comparison(old, new, focus_client="foghttp", top_n=1)
    assert comparison.resource_summary.old_rss_mb_max == OBSERVED_PEAK
    assert len(comparison.top_improvements) == 1
    assert len(comparison.resource_coverage) == MATCHED_ROWS
    assert "1/3 (partial)" in render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)
    assert any("second-case" in item.label for item in comparison.resource_coverage)


def test_legacy_zero_is_not_reinterpreted_as_missing_or_complete(tmp_path: Path) -> None:
    row = ordinary_resource_row("requests", 0)
    old = write_report(tmp_path, "old.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    new = write_report(tmp_path, "new.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    comparison = build_comparison(old, new, focus_client="foghttp", top_n=1)

    assert comparison.resource_summary.old_rss_mb_max == 0
    assert comparison.resource_coverage[0].old == {}
    assert "| resource metrics | unknown | unknown |" in render_compare_markdown(
        load_report_template("compare_report.md.j2"),
        comparison,
    )
    assert "historical missingness cannot be reconstructed" in render_compare_markdown(
        load_report_template("compare_report.md.j2"),
        comparison,
    )


@pytest.mark.parametrize("metric", RESOURCE_FIELDS)
@pytest.mark.parametrize("value", [True, False, "bad", float("nan"), float("inf")])
def test_resource_loader_rejects_malformed_measurements(tmp_path: Path, metric: str, value: object) -> None:
    row = ordinary_resource_row("requests", 0)
    row[metric] = value
    path = write_report(tmp_path, "invalid.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    with pytest.raises(ValueError, match=re.escape(f"aggregate[0].{metric}")):
        load_benchmark_report(path)


@pytest.mark.parametrize(
    ("coverage", "error_path"),
    [
        (None, "aggregate[0].resource_coverage"),
        ({"rss_mb_max": None}, "aggregate[0].resource_coverage.rss_mb_max"),
        (
            {"rss_mb_max": {"available": True, "expected": 1, "unavailable_reasons": []}},
            "aggregate[0].resource_coverage.rss_mb_max.available",
        ),
        (
            {"rss_mb_max": {"available": 1, "expected": False, "unavailable_reasons": []}},
            "aggregate[0].resource_coverage.rss_mb_max.expected",
        ),
        (
            {"rss_mb_max": {"available": -1, "expected": 1, "unavailable_reasons": []}},
            "aggregate[0].resource_coverage.rss_mb_max.available",
        ),
        (
            {"rss_mb_max": {"available": 2, "expected": 1, "unavailable_reasons": []}},
            "aggregate[0].resource_coverage.rss_mb_max",
        ),
        (
            {"rss_mb_max": {"available": 0, "expected": 1, "unavailable_reasons": [False]}},
            "aggregate[0].resource_coverage.rss_mb_max.unavailable_reasons",
        ),
        (
            {"rss_mb_max": {"available": 0, "expected": 1, "unavailable_reasons": "permission denied"}},
            "aggregate[0].resource_coverage.rss_mb_max.unavailable_reasons",
        ),
    ],
)
def test_resource_loader_rejects_malformed_coverage(
    tmp_path: Path,
    coverage: object,
    error_path: str,
) -> None:
    row = ordinary_resource_row("requests", None)
    row["resource_coverage"] = coverage
    path = write_report(tmp_path, "invalid.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    with pytest.raises(ValueError, match=re.escape(error_path)):
        load_benchmark_report(path)


def test_negative_creation_delta_remains_an_observation(tmp_path: Path) -> None:
    row = ordinary_resource_row("client-creation", -1)
    path = write_report(tmp_path, "creation.json", aggregate=[row], suite="client-creation", foghttp_version="0.4.2")
    loaded = load_benchmark_report(path).rows[0]
    assert loaded.rss_mb == -1
    assert loaded.threads == -1
    assert loaded.fds == -1


@pytest.mark.parametrize(
    ("suite", "count"),
    [("requests", EXACT_INTEGER_COUNT), ("client-creation", -EXACT_INTEGER_COUNT)],
)
def test_integer_resource_counts_preserve_exact_precision(tmp_path: Path, suite: BenchmarkSuite, count: int) -> None:
    row = ordinary_resource_row(suite, 0)
    fields = (
        ("peak_threads_delta_max", "peak_fds_delta_max") if suite == "client-creation" else ("threads_max", "fds_max")
    )
    for metric in fields:
        row[metric] = count
    path = write_report(tmp_path, "counts.json", aggregate=[row], suite=suite, foghttp_version="0.4.2")

    loaded = load_benchmark_report(path).rows[0]

    assert loaded.threads == count
    assert loaded.fds == count


@pytest.mark.parametrize(
    ("reason", "rendered_reason"),
    [("permission denied", "permission denied"), ("probe | denied\nretry", r"probe \| denied<br>retry")],
)
def test_lifecycle_preserves_client_unavailability_without_inventing_coverage(
    tmp_path: Path,
    reason: str,
    rendered_reason: str,
) -> None:
    row = ordinary_resource_row("response-streaming", 0)
    row.update(
        profile="lifecycle",
        configuration={"body_bytes": 1024},
        resources={
            "client": {"sampled_peak_fds_max": None, "unavailable": {"fds": [reason]}},
            "server": {"sampled_peak_fds_max": 100, "unavailable": {"fds": ["server-only reason"]}},
        },
    )
    old = write_report(tmp_path, "old.json", aggregate=[row], suite="response-streaming", foghttp_version="0.4.2")
    new = write_report(tmp_path, "new.json", aggregate=[row], suite="response-streaming", foghttp_version="0.4.2")
    comparison = build_comparison(old, new, focus_client="foghttp", top_n=1)
    observation = comparison.resource_coverage[0]
    assert observation.old == {}
    assert observation.old_unavailable_reasons["sampled_peak_fds_max"] == (reason,)
    serialized = json.loads(json.dumps(asdict(comparison), default=str))
    assert serialized["resource_coverage"][0]["old_unavailable_reasons"]["sampled_peak_fds_max"] == [reason]
    assert comparison.resource_summary.old_fds_max is None
    markdown = render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)
    assert rendered_reason in markdown
    assert "server-only reason" not in markdown
