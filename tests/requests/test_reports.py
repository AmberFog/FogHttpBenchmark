from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    REQUESTS_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs, RunResult
from foghttp_benchmark.reports import aggregate_results, write_reports


EXPECTED_ERRORS_TOTAL = 7
EXPECTED_WARMUP_ERRORS_TOTAL = 3


def test_request_aggregate_preserves_error_type_totals(error_results: list[RunResult]) -> None:
    rows = aggregate_results(error_results)

    assert len(rows) == 1
    payload = asdict(rows[0])
    assert payload["errors_total"] == EXPECTED_ERRORS_TOTAL
    assert payload["warmup_errors_total"] == EXPECTED_WARMUP_ERRORS_TOTAL
    assert payload["error_types"] == {
        "RequestError": 5,
        "TimeoutError": 1,
        "check_failed": 1,
    }
    assert payload["warmup_error_types"] == {
        "RequestError": 1,
        "TimeoutError": 2,
    }


@pytest.mark.parametrize(
    ("suite", "scenario"),
    [(REQUESTS_SUITE, "post-echo-64k"), (COMPRESSED_RESPONSE_SUITE, "gzip-64k")],
)
def test_request_report_serializes_measured_and_warmup_error_types(
    tmp_path: Path,
    suite: str,
    scenario: str,
    error_results: list[RunResult],
) -> None:
    results = [replace(result, scenario=scenario) for result in error_results]
    args = BenchmarkArgs(
        suite=suite,
        clients="foghttp",
        modes="async",
        concurrency="10",
        requests=100,
        warmup=10,
        repeats=2,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(tmp_path),
        scenarios=scenario,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )

    write_reports(results, {}, args)

    payload = json.loads((tmp_path / "latest.json").read_text())
    assert payload["metadata"]["suite"] == suite
    row = payload["aggregate"][0]
    assert row["errors_total"] == EXPECTED_ERRORS_TOTAL
    assert row["warmup_errors_total"] == EXPECTED_WARMUP_ERRORS_TOTAL
    assert row["error_types"] == {"RequestError": 5, "TimeoutError": 1, "check_failed": 1}
    assert row["warmup_error_types"] == {"RequestError": 1, "TimeoutError": 2}
    assert payload["runs"] == [asdict(result) for result in results]
    markdown = (tmp_path / "latest.md").read_text()
    assert "warmup error types" in markdown
    assert "'check_failed': 1" in markdown
    assert "'TimeoutError': 2" in markdown
