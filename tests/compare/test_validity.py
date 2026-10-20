import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.reports import build_comparison
from foghttp_benchmark.rendering import load_report_template, render_compare_markdown
from tests.compare.factories import request_row, write_report


@pytest.mark.parametrize("status", ["valid", "warning"])
def test_stale_validity_cannot_rank_failed_rows(tmp_path: Path, status: str) -> None:
    good_row = request_row("zapros-pyreqwest", ok_req_s=100.0, p95_ms=1.0)
    good_row["mode"] = "sync"
    old = write_report(tmp_path, "old.json", aggregate=[good_row], suite="requests", foghttp_version="0.4.1")
    failed_row = dict(good_row)
    failed_row.update(
        errors_total=100,
        error_types={"RuntimeError": 100},
        ok_req_s_median=0.0,
    )
    new = write_report(tmp_path, "new.json", aggregate=[failed_row], suite="requests", foghttp_version="0.4.1")
    payload = json.loads(new.read_text())
    payload["metadata"]["validity"] = {"status": status, "can_compare": True, "reasons": []}
    new.write_text(json.dumps(payload))

    comparison = build_comparison(old, new, focus_client="zapros-pyreqwest", top_n=1)
    markdown = render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)

    assert comparison.validity.new_status == "needs-rerun"
    assert comparison.validity.blocks_strong_conclusions
    assert comparison.wins is None
    assert "Competitive Position" not in markdown
    assert "Validity Warning" in markdown


def test_compatibility_warning_blocks_competitive_position(tmp_path: Path) -> None:
    good_row = request_row("zapros-pyreqwest", ok_req_s=100.0, p95_ms=1.0)
    good_row["mode"] = "sync"
    old = write_report(tmp_path, "old.json", aggregate=[good_row], suite="requests", foghttp_version="0.4.1")
    affected_row = dict(good_row)
    affected_row.update(warmup_errors_total=1, warmup_error_types={"RuntimeError": 1})
    new = write_report(tmp_path, "new.json", aggregate=[affected_row], suite="requests", foghttp_version="0.4.1")

    comparison = build_comparison(old, new, focus_client="zapros-pyreqwest", top_n=1)
    markdown = render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)

    assert comparison.validity.new_status == "warning"
    assert comparison.validity.blocks_strong_conclusions
    assert comparison.wins is None
    assert "does not permit performance comparison" in markdown
    assert "At least one input report is `needs-rerun` or `invalid`" not in markdown
