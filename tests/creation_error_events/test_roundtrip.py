from pathlib import Path

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.models import ClientCreationResult
from foghttp_benchmark.report_schema.decoding import load_report
from tests.creation_error_events.actions import creation_args, write_failure_child
from tests.creation_error_events.cases import CreationFailureCase


def test_creation_error_events_survive_writer_comparison_and_parent_merge(
    tmp_path: Path,
    creation_result: ClientCreationResult,
    failure_case: CreationFailureCase,
) -> None:
    assert creation_result.error_types == failure_case.expected_error_types
    assert creation_result.errors == sum(failure_case.expected_error_types.values())
    child = write_failure_child(tmp_path / "child", creation_result)
    source_path = Path(child.report_path or "")
    source = source_path.read_bytes()

    decoded = load_report(source_path)
    report = load_benchmark_report(source_path)
    compared = compare_reports(report, report, focus_client=creation_result.client, top_n=1)
    write_isolation_report(
        creation_args(tmp_path / "parent"),
        [child],
        {},
        child_cooldown_s=0.0,
        finalizer=get_suite("client-creation").finalize_report,
    )
    parent_path = tmp_path / "parent" / "latest.json"
    parent = load_report(parent_path)
    parent_report = load_benchmark_report(parent_path)

    assert decoded.aggregate_rows[0]["errors_total"] == creation_result.errors * 2
    assert decoded.run_rows[0]["error_types"] == failure_case.expected_error_types
    assert parent.aggregate_rows[0]["errors_total"] == creation_result.errors * 2
    assert parent.run_rows[0]["errors"] == creation_result.errors
    assert parent.run_rows[0]["error_types"] == failure_case.expected_error_types
    assert parent.run_rows[1]["error_types"] == failure_case.expected_error_types
    assert report.validity.status == "needs-rerun"
    assert report.validity.can_compare is False
    assert parent_report.validity.status == "needs-rerun"
    assert parent_report.validity.can_compare is False
    assert compared.validity.blocks_strong_conclusions is True
    assert compared.wins is None
    assert source_path.read_bytes() == source
