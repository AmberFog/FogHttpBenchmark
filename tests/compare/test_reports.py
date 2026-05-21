from pathlib import Path

import pytest
from typer.testing import CliRunner

from foghttp_benchmark.cli import app
from foghttp_benchmark.compare.reports import build_comparison, render_compare_markdown
from tests.compare.factories import (
    legacy_request_row,
    one_upstream_row,
    request_builder_row,
    request_row,
    resource_row,
    write_report,
)


FOGHTTP_RATIO = 1.2
OLD_RESOURCE_ERRORS = 100


def test_compare_infers_legacy_request_reports(tmp_path: Path) -> None:
    old_report = write_report(
        tmp_path,
        "old.json",
        aggregate=[
            legacy_request_row("foghttp", ok_req_s=100.0, p95_ms=2.0),
            legacy_request_row("httpx", ok_req_s=90.0, p95_ms=3.0),
        ],
        foghttp_version="0.1.3",
    )
    new_report = write_report(
        tmp_path,
        "new.json",
        aggregate=[
            request_row("foghttp", ok_req_s=120.0, p95_ms=1.0),
            request_row("httpx", ok_req_s=95.0, p95_ms=2.0),
        ],
        foghttp_version="0.2.0",
    )

    comparison = build_comparison(old_report, new_report, focus_client="foghttp", top_n=1)
    markdown = render_compare_markdown(comparison)

    assert comparison.metadata.suite == "requests"
    assert comparison.metadata.old_focus_version == "0.1.3"
    assert comparison.metadata.new_focus_version == "0.2.0"
    assert comparison.overall.rows == 1
    assert comparison.overall.primary_geomean_ratio == pytest.approx(FOGHTTP_RATIO)
    assert comparison.wins is not None
    assert "Competitive Position" in markdown
    assert "+20.0%" in markdown


def test_resource_reports_skip_competitive_position(tmp_path: Path) -> None:
    old_report = write_report(
        tmp_path,
        "old.json",
        aggregate=[resource_row(ok_requests=500, errors=OLD_RESOURCE_ERRORS)],
        suite="resource-backpressure",
        foghttp_version="0.2.0",
    )
    new_report = write_report(
        tmp_path,
        "new.json",
        aggregate=[resource_row(ok_requests=600, errors=0)],
        suite="resource-backpressure",
        foghttp_version="0.2.1",
    )

    comparison = build_comparison(old_report, new_report, focus_client="foghttp", top_n=1)
    markdown = render_compare_markdown(comparison)

    assert comparison.wins is None
    assert "Competitive Position" not in markdown
    assert comparison.resource_summary.old_errors_total == OLD_RESOURCE_ERRORS
    assert comparison.resource_summary.new_errors_total == 0


def test_compare_infers_one_upstream_reports(tmp_path: Path) -> None:
    old_report = write_report(
        tmp_path,
        "old.json",
        aggregate=[
            one_upstream_row("foghttp", ok_req_s=100.0, p95_ms=2.0),
            one_upstream_row("httpx", ok_req_s=90.0, p95_ms=3.0),
        ],
        foghttp_version="0.3.0",
    )
    new_report = write_report(
        tmp_path,
        "new.json",
        aggregate=[
            one_upstream_row("foghttp", ok_req_s=110.0, p95_ms=1.5),
            one_upstream_row("httpx", ok_req_s=115.0, p95_ms=2.5),
        ],
        foghttp_version="0.3.1",
    )

    comparison = build_comparison(old_report, new_report, focus_client="foghttp", top_n=1)
    markdown = render_compare_markdown(comparison)

    assert comparison.metadata.suite == "one-upstream"
    assert comparison.overall.primary_geomean_ratio == pytest.approx(1.1)
    assert comparison.wins is not None
    assert comparison.wins.new_wins == 0
    assert "defaults-get" in markdown


def test_compare_infers_request_builder_reports(tmp_path: Path) -> None:
    old_report = write_report(
        tmp_path,
        "old.json",
        aggregate=[
            request_builder_row("foghttp", ops_s=100_000.0, p95_ms=0.02),
            request_builder_row("httpx", ops_s=90_000.0, p95_ms=0.03),
        ],
        foghttp_version="0.3.0",
    )
    new_report = write_report(
        tmp_path,
        "new.json",
        aggregate=[
            request_builder_row("foghttp", ops_s=120_000.0, p95_ms=0.01),
            request_builder_row("httpx", ops_s=110_000.0, p95_ms=0.02),
        ],
        foghttp_version="0.3.1",
    )

    comparison = build_comparison(old_report, new_report, focus_client="foghttp", top_n=1)
    markdown = render_compare_markdown(comparison)

    assert comparison.metadata.suite == "request-builder"
    assert comparison.overall.primary_geomean_ratio == pytest.approx(1.2)
    assert comparison.wins is not None
    assert "default-params" in markdown


def test_compare_rejects_mismatched_suites(tmp_path: Path) -> None:
    old_report = write_report(
        tmp_path,
        "old.json",
        aggregate=[request_row("foghttp", ok_req_s=100.0, p95_ms=2.0)],
        suite="requests",
        foghttp_version="0.2.0",
    )
    new_report = write_report(
        tmp_path,
        "new.json",
        aggregate=[resource_row(ok_requests=600, errors=0)],
        suite="resource-backpressure",
        foghttp_version="0.2.1",
    )

    with pytest.raises(ValueError, match="same benchmark suite"):
        build_comparison(old_report, new_report, focus_client="foghttp", top_n=1)


def test_cli_rejects_invalid_top_value() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["compare", "old.json", "new.json", "--top", "0"])

    assert result.exit_code != 0
    assert "top must be at least 1" in result.output
