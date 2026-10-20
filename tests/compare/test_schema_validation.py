import json
from pathlib import Path
import re

import pytest
from typer.testing import CliRunner

from foghttp_benchmark.cli import app
from foghttp_benchmark.compare.loading import load_benchmark_report
from tests.compare.factories import request_row, write_report


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ok_req_s_median", None),
        ("ok_req_s_median", True),
        ("ok_req_s_median", "100.0"),
        ("ok_req_s_median", "NaN"),
        ("ok_req_s_median", "Infinity"),
        ("ok_req_s_median", float("nan")),
        ("ok_req_s_median", float("inf")),
        ("ok_req_s_median", float("-inf")),
        ("client", None),
        ("client", False),
        ("client", ""),
        ("concurrency", True),
        ("concurrency", 1.5),
        ("concurrency", "10"),
        ("requests", 0),
        ("repeats", -1),
        ("errors_total", -1),
        ("errors_total", 0.5),
        ("errors_total", False),
        ("errors_total", "0"),
        ("warmup_errors_total", True),
        ("error_types", {"RuntimeError": 1}),
        ("warmup_error_types", {"RuntimeError": 1}),
    ],
)
def test_comparison_loader_rejects_malformed_required_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    row = request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)
    row[field] = value
    path = write_report(tmp_path, "corrupt.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")

    with pytest.raises(ValueError, match=re.escape(f"aggregate[0].{field}")):
        load_benchmark_report(path)


@pytest.mark.parametrize("field", ["client", "scenario", "ok_req_s_median", "errors_total", "requests", "repeats"])
def test_comparison_does_not_replace_missing_required_fields_with_defaults(tmp_path: Path, field: str) -> None:
    row = request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)
    del row[field]
    path = write_report(tmp_path, "missing.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")

    with pytest.raises(ValueError, match=re.escape(f"aggregate[0].{field}")):
        load_benchmark_report(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("suite", "future-suite"), ("report_schema_version", 99), ("report_schema_version", True)],
)
def test_comparison_rejects_unknown_explicit_contracts_instead_of_inferring_defaults(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    row = request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)
    path = write_report(tmp_path, "unknown.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    payload = json.loads(path.read_text())
    payload["metadata"][field] = value
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match=re.escape(f"metadata.{field}")):
        load_benchmark_report(path)


@pytest.mark.parametrize("value", [None, True, "NaN", -1.0])
def test_compare_cli_does_not_publish_rankings_for_a_corrupt_report(tmp_path: Path, value: object) -> None:
    row = request_row("foghttp", ok_req_s=100.0, p95_ms=1.0)
    old = write_report(tmp_path, "old.json", aggregate=[row], suite="requests", foghttp_version="0.4.2")
    corrupt_row = {**row, "ok_req_s_median": value}
    new = write_report(tmp_path, "corrupt.json", aggregate=[corrupt_row], suite="requests", foghttp_version="0.4.2")
    output = tmp_path / "comparison.md"

    result = CliRunner().invoke(app, ["compare", str(old), str(new), "--output", str(output)])

    assert result.exit_code != 0
    assert "ok_req_s_median" in result.output
    assert "Competitive Position" not in result.output
    assert not output.exists()
