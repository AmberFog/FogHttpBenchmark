from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from foghttp_benchmark.cli import app
from foghttp_benchmark.compare.analysis import compare_reports, focus_rows_by_identity, wins_for_report
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.reports import build_comparison
from tests.aggregate_identity.factories import changed_measurement, competitor_rows, multiple_case_rows, saved_report
from tests.compare.factories import request_row
from tests.report_schema.ordinary_fixtures import ORDINARY_SUITES


CASE_COUNT = 2


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_unique_aggregate_permutation_does_not_change_comparison(tmp_path: Path, suite: str) -> None:
    rows = multiple_case_rows(suite)
    old_path = saved_report(tmp_path / "old", suite, rows)
    new_path = saved_report(tmp_path / "new", suite, list(reversed(rows)))

    normal = build_comparison(old_path, old_path, focus_client="foghttp", top_n=10)
    permuted = build_comparison(old_path, new_path, focus_client="foghttp", top_n=10)

    assert replace(permuted, metadata=normal.metadata) == normal
    assert normal.overall.rows == CASE_COUNT


def test_equal_competitor_values_have_order_independent_wins_and_rank(tmp_path: Path) -> None:
    rows = [request_row(client, ok_req_s=100.0, p95_ms=1.0) for client in ("foghttp", "httpx")]
    old_path = saved_report(tmp_path / "old", "requests", rows)
    reversed_path = saved_report(tmp_path / "reversed", "requests", list(reversed(rows)))

    normal = build_comparison(old_path, old_path, focus_client="foghttp", top_n=10)
    permuted = build_comparison(old_path, reversed_path, focus_client="foghttp", top_n=10)

    assert normal.wins is not None
    assert replace(permuted, metadata=normal.metadata) == normal


@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize("client", ["foghttp", "httpx"])
@pytest.mark.parametrize("existing_output", [False, True])
def test_compare_cli_rejects_duplicate_focus_or_competitor_without_publishing(
    tmp_path: Path,
    side: str,
    client: str,
    *,
    existing_output: bool,
) -> None:
    rows = competitor_rows("requests")
    duplicate = changed_measurement("requests", next(row for row in rows if row["client"] == client))
    old_path = saved_report(tmp_path / "old", "requests", [*rows, duplicate] if side == "old" else rows)
    new_path = saved_report(tmp_path / "new", "requests", [*rows, duplicate] if side == "new" else rows)
    output = tmp_path / "comparison.md"
    previous = "previous comparison retained\n"
    if existing_output:
        output.write_text(previous)

    result = CliRunner().invoke(
        app,
        ["compare", str(old_path), str(new_path), "--output", str(output)],
        env={"COLUMNS": "1000"},
    )

    assert result.exit_code != 0
    assert "Duplicate aggregate identity" in result.output
    assert str(old_path if side == "old" else new_path) in result.output
    assert "Competitive Position" not in result.output
    if existing_output:
        assert output.read_text() == previous
    else:
        assert not output.exists()


@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize("client", ["foghttp", "httpx"])
@pytest.mark.parametrize("primary_value", [None, 100.0])
def test_prepared_comparison_models_cannot_bypass_duplicate_validation(
    tmp_path: Path,
    side: str,
    client: str,
    primary_value: float | None,
) -> None:
    path = saved_report(tmp_path, "requests", competitor_rows("requests"))
    valid = load_benchmark_report(path)
    duplicate = next(row for row in valid.rows if row.client == client)
    invalid = replace(valid, rows=[*valid.rows, replace(duplicate, primary_value=primary_value)])

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        compare_reports(
            invalid if side == "old" else valid,
            invalid if side == "new" else valid,
            focus_client="foghttp",
            top_n=10,
        )


@pytest.mark.parametrize("client", ["foghttp", "httpx"])
def test_nullable_duplicate_cannot_bypass_direct_focus_or_wins_selection(tmp_path: Path, client: str) -> None:
    path = saved_report(tmp_path, "requests", competitor_rows("requests"))
    valid = load_benchmark_report(path)
    duplicate = next(row for row in valid.rows if row.client == client)
    invalid = replace(valid, rows=[*valid.rows, replace(duplicate, primary_value=None)])

    for selection in (focus_rows_by_identity, wins_for_report):
        with pytest.raises(ValueError, match="Duplicate aggregate identity"):
            selection(invalid, "foghttp")


@pytest.mark.parametrize("values", [(50.0, 200.0), (200.0, 50.0)])
def test_conflicting_duplicate_never_selects_an_arbitrary_ratio(tmp_path: Path, values: tuple[float, float]) -> None:
    baseline = saved_report(
        tmp_path / "old",
        "requests",
        [request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)],
    )
    conflicting = saved_report(
        tmp_path / "new",
        "requests",
        [request_row("foghttp", ok_req_s=value, p95_ms=1.0) for value in values],
    )

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        build_comparison(baseline, conflicting, focus_client="foghttp", top_n=10)
