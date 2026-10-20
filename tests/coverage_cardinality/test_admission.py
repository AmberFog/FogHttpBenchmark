from dataclasses import replace
import json
from pathlib import Path
import re

import pytest
from typer.testing import CliRunner

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.cli import app
from foghttp_benchmark.isolation.reports import write_isolation_report
from tests.isolation.test_reports import child_result
from tests.resource.factories import benchmark_args
from tests.resource_metrics.cases import ResourceReportCase
from tests.resource_metrics.report_actions import report_payload, write_resource_case


@pytest.mark.parametrize("existing_output", [False, True])
def test_comparison_rejects_forged_complete_coverage_before_publishing(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    *,
    existing_output: bool,
) -> None:
    valid = write_resource_case(resource_case, tmp_path / "valid", [None, 0])
    corrupt = write_resource_case(resource_case, tmp_path / "corrupt", [None, 0])
    payload = report_payload(corrupt)
    metric = resource_case.metrics[0].aggregate
    payload["aggregate"][0]["resource_coverage"][metric]["expected"] = 1
    corrupt.write_text(json.dumps(payload))
    sources = {path: path.read_bytes() for path in (valid, corrupt)}
    output = tmp_path / "comparison.md"
    previous = "previous comparison retained\n"
    if existing_output:
        output.write_text(previous)

    result = CliRunner().invoke(
        app,
        ["compare", str(valid), str(corrupt), "--output", str(output)],
        env={"COLUMNS": "1000"},
    )

    assert result.exit_code != 0
    assert str(corrupt) in result.output
    assert metric in result.output
    assert "Competitive Position" not in result.output
    if existing_output:
        assert output.read_text() == previous
    else:
        assert not output.exists()
    assert {path: path.read_bytes() for path in sources} == sources


@pytest.mark.parametrize("existing_output", [False, True])
def test_parent_rejects_forged_complete_coverage_before_publishing(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    *,
    existing_output: bool,
) -> None:
    child = write_resource_case(resource_case, tmp_path / "child", [None, 0])
    payload = report_payload(child)
    metric = resource_case.metrics[0].aggregate
    payload["aggregate"][0]["resource_coverage"][metric]["expected"] = 1
    child.write_text(json.dumps(payload))
    source = child.read_bytes()
    parent = tmp_path / "parent"
    previous = {"latest.json": b"previous JSON\n", "latest.md": b"previous Markdown\n"} if existing_output else {}
    if existing_output:
        parent.mkdir()
        for name, content in previous.items():
            (parent / name).write_bytes(content)
    args = replace(benchmark_args(parent), suite=resource_case.suite, isolation="per-client")

    with pytest.raises(ValueError, match=re.escape(metric)) as error:
        write_isolation_report(
            args,
            [child_result(1, "foghttp", child)],
            {},
            finalizer=get_suite(args.suite).finalize_report,
            child_cooldown_s=0.0,
        )

    assert str(child) in str(error.value)
    assert child.read_bytes() == source
    assert {path.name: path.read_bytes() for path in parent.glob("*")} == previous
