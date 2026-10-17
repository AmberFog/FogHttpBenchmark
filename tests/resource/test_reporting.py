from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.constants import RESOURCE_BACKPRESSURE_SUITE
from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.resource.reporting.aggregation import aggregate_resource_results
from foghttp_benchmark.resource.reporting.reports import write_resource_reports
from foghttp_benchmark.validity.classification import classify_report_validity
from tests.resource.factories import BUFFERED_RESPONSE_BUDGET, benchmark_args, resource_result


BUFFERED_RESPONSE_BUDGET_REJECTIONS = 5
EXPECTED_WARMUP_ERRORS_TOTAL = 3


def test_resource_aggregation_includes_buffered_budget_metrics() -> None:
    rows = aggregate_resource_results(
        [
            resource_result(
                peak_buffered_response_bytes=65_536,
                buffered_response_budget_rejections=3,
                buffered_response_bytes=0,
            ),
            resource_result(
                peak_buffered_response_bytes=BUFFERED_RESPONSE_BUDGET,
                buffered_response_budget_rejections=BUFFERED_RESPONSE_BUDGET_REJECTIONS,
                buffered_response_bytes=0,
            ),
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.max_buffered_response_bytes == BUFFERED_RESPONSE_BUDGET
    assert row.peak_buffered_response_bytes_max == BUFFERED_RESPONSE_BUDGET
    assert row.final_buffered_response_budget_rejections_max == BUFFERED_RESPONSE_BUDGET_REJECTIONS
    assert row.final_buffered_response_bytes_max == 0


@pytest.mark.parametrize(
    ("scenario", "error_type"),
    [
        ("aggregate-buffered-budget", "ResponseBodyBudgetExceededError"),
        ("pending-queue-full", "PoolTimeout"),
        ("pool-timeout-recovery", "PoolTimeout"),
        ("response-body-limit", "ResponseBodyTooLargeError"),
    ],
)
def test_resource_aggregation_preserves_expected_warmup_errors_for_validity(
    scenario: str,
    error_type: str,
) -> None:
    results = [
        replace(
            resource_result(),
            scenario=scenario,
            repeat=repeat,
            error_types={error_type: 3},
            warmup=3,
            warmup_errors=repeat + 1,
            warmup_error_types={error_type: repeat + 1},
        )
        for repeat in range(2)
    ]
    row = asdict(aggregate_resource_results(results)[0])

    summary = classify_report_validity(suite=RESOURCE_BACKPRESSURE_SUITE, aggregate_rows=[row])

    assert row["warmup_errors_total"] == EXPECTED_WARMUP_ERRORS_TOTAL
    assert row["warmup_error_types"] == {error_type: EXPECTED_WARMUP_ERRORS_TOTAL}
    assert summary.status == "valid"
    assert summary.can_compare
    assert summary.reasons == ()


@pytest.mark.parametrize(
    "warmup_error_types",
    [
        {"ResponseBodyBudgetExceededError": 1, "RuntimeError": 1},
        {"RuntimeError": 2},
        {},
    ],
    ids=["mixed", "unknown", "missing"],
)
def test_resource_aggregation_keeps_unknown_warmup_errors_blocking(
    warmup_error_types: dict[str, int],
) -> None:
    first = replace(
        resource_result(),
        warmup=3,
        warmup_errors=1,
        warmup_error_types={"ResponseBodyBudgetExceededError": 1},
    )
    second = replace(first, repeat=2, warmup_errors=2, warmup_error_types=warmup_error_types)
    row = asdict(aggregate_resource_results([first, second])[0])

    summary = classify_report_validity(suite=RESOURCE_BACKPRESSURE_SUITE, aggregate_rows=[row])

    assert row["warmup_errors_total"] == EXPECTED_WARMUP_ERRORS_TOTAL
    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert [reason.code for reason in summary.reasons] == ["unexpected_warmup_errors"]


def test_resource_legacy_aggregate_without_warmup_error_types_remains_blocking() -> None:
    result = replace(
        resource_result(),
        warmup=1,
        warmup_errors=1,
        warmup_error_types={"ResponseBodyBudgetExceededError": 1},
    )
    row = asdict(aggregate_resource_results([result])[0])
    del row["warmup_error_types"]

    summary = classify_report_validity(suite=RESOURCE_BACKPRESSURE_SUITE, aggregate_rows=[row])

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert [reason.code for reason in summary.reasons] == ["unexpected_warmup_errors"]


def test_resource_writer_and_isolated_parent_keep_warmup_error_types(tmp_path: Path) -> None:
    result = replace(
        resource_result(),
        warmup=3,
        warmup_errors=3,
        warmup_error_types={"ResponseBodyBudgetExceededError": 3},
    )
    child_dir = tmp_path / "child"
    write_resource_reports([result], {}, benchmark_args(child_dir))
    child_report = child_dir / "latest.json"
    child_payload = json.loads(child_report.read_text())
    child = ChildProcessResult(
        sequence=1,
        client="foghttp",
        scenario=result.scenario,
        output_dir=str(child_dir),
        report_path=str(child_report),
        command=["python", "-m", "foghttp_benchmark"],
        returncode=0,
        duration_s=1.0,
        peaks=ChildResourcePeaks(rss_mb=60.0, threads=3, fds=12),
        stdout_tail="",
        stderr_tail="",
    )
    parent_dir = tmp_path / "parent"

    write_isolation_report(benchmark_args(parent_dir), [child], {}, child_cooldown_s=0.0)

    parent_payload = json.loads((parent_dir / "latest.json").read_text())
    for payload in (child_payload, parent_payload):
        assert payload["aggregate"][0]["warmup_error_types"] == result.warmup_error_types
        assert payload["runs"][0]["warmup_error_types"] == result.warmup_error_types
        assert payload["metadata"]["validity"]["status"] == "valid"
        assert payload["metadata"]["validity"]["can_compare"]
