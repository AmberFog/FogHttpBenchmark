from dataclasses import replace
from pathlib import Path

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.isolation.reports import write_isolation_report
from tests.isolation.test_reports import child_result
from tests.resource.factories import benchmark_args
from tests.resource_metrics.cases import RESOURCE_REPORT_CASES, RESOURCE_SCHEMA_VERSION, ResourceReportCase
from tests.resource_metrics.report_actions import (
    remove_resource_coverage,
    report_payload,
    resource_results,
    write_resource_case,
    write_resource_results,
)


def test_isolation_merge_preserves_nullable_resources_and_partial_coverage(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    observations: tuple[int | None, ...],
) -> None:
    child_path = write_resource_case(resource_case, tmp_path / "child", observations)
    child_payload = report_payload(child_path)
    parent_dir = tmp_path / "parent"
    args = replace(benchmark_args(parent_dir), suite=resource_case.suite, isolation="per-client")

    write_isolation_report(
        args,
        [child_result(1, "foghttp", child_path)],
        {},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=0.0,
    )

    parent_path = parent_dir / "latest.json"
    parent_payload = report_payload(parent_path)
    assert parent_payload["metadata"]["resource_metric_schema_version"] == RESOURCE_SCHEMA_VERSION
    assert parent_payload["aggregate"] == child_payload["aggregate"]
    assert parent_payload["runs"] == child_payload["runs"]
    assert load_benchmark_report(parent_path).aggregate_rows == child_payload["aggregate"]
    markdown = (parent_dir / "latest.md").read_text()
    assert "Resource observation coverage" in markdown
    assert f"{sum(value is not None for value in observations)} / {len(observations)}" in markdown


def test_mixed_isolation_merge_preserves_legacy_zeros_and_discloses_unknown_coverage(tmp_path: Path) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == "requests")
    current_path = write_resource_case(case, tmp_path / "current", [None])
    current_payload = report_payload(current_path)
    legacy_dir = tmp_path / "legacy"
    write_resource_results(
        case,
        legacy_dir,
        [replace(result, client="httpx") for result in resource_results(case, [0])],
    )
    legacy_path = legacy_dir / "latest.json"
    legacy_payload = remove_resource_coverage(legacy_path)
    parent_dir = tmp_path / "parent"
    args = replace(benchmark_args(parent_dir), suite=case.suite, isolation="per-client")

    write_isolation_report(
        args,
        [child_result(1, "foghttp", current_path), child_result(2, "httpx", legacy_path)],
        {},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=0.0,
    )

    payload = report_payload(parent_dir / "latest.json")
    assert "resource_metric_schema_version" not in payload["metadata"]
    assert payload["metadata"]["isolation"]["children"][0]["resource_metric_schema_version"] == RESOURCE_SCHEMA_VERSION
    assert "resource_metric_schema_version" not in payload["metadata"]["isolation"]["children"][1]
    assert payload["aggregate"] == current_payload["aggregate"] + legacy_payload["aggregate"]
    assert payload["runs"] == current_payload["runs"] + legacy_payload["runs"]
    for metric in case.metrics:
        assert payload["aggregate"][0][metric.aggregate] is None
        assert payload["aggregate"][1][metric.aggregate] == 0
    assert report_payload(current_path) == current_payload
    assert report_payload(legacy_path) == legacy_payload
    markdown = (parent_dir / "latest.md").read_text().split("## Resource observation coverage", maxsplit=1)[1]
    assert "Resource metric schema: `2`" not in markdown
    legacy_row = next(line for line in markdown.splitlines() if "| httpx |" in line)
    assert legacy_payload["aggregate"][0]["scenario"] in legacy_row
    assert "unknown" in legacy_row.lower()
