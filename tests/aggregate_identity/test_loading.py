from copy import deepcopy
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.report_schema.decoding import load_report
from tests.aggregate_identity.factories import changed_measurement, competitor_rows, repeated_runs, saved_report
from tests.report_schema.ordinary_fixtures import ORDINARY_SUITES, ordinary_aggregate


ROW_COUNT = 2


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_saved_aggregate_duplicates_are_rejected_before_comparison(
    tmp_path: Path,
    suite: str,
    *,
    conflicting: bool,
    reverse: bool,
) -> None:
    row = ordinary_aggregate(suite)
    duplicate = changed_measurement(suite, row) if conflicting else deepcopy(row)
    rows = [row, duplicate]
    if reverse:
        rows.reverse()
    path = saved_report(tmp_path, suite, rows)
    source = path.read_bytes()

    for loader in (load_report, load_benchmark_report):
        with pytest.raises(ValueError, match="Duplicate aggregate identity") as error:
            loader(path)

        message = str(error.value)
        assert str(path) in message
        assert "aggregate[0]" in message
        assert "aggregate[1]" in message
    assert path.read_bytes() == source


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_run_repeats_do_not_count_as_aggregate_duplicates(tmp_path: Path, suite: str) -> None:
    runs = repeated_runs(suite)
    path = saved_report(tmp_path, suite, [ordinary_aggregate(suite)], runs=runs)

    report = load_report(path)
    comparison_report = load_benchmark_report(path)

    assert report.run_rows == runs
    assert len(report.aggregate_rows) == 1
    assert len(comparison_report.rows) == 1


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_clients_in_the_same_competitive_group_have_distinct_identities(tmp_path: Path, suite: str) -> None:
    path = saved_report(tmp_path, suite, competitor_rows(suite))

    report = load_benchmark_report(path)

    assert len(report.rows) == ROW_COUNT
    assert report.rows[0].group == report.rows[1].group
    assert report.rows[0].identity != report.rows[1].identity
    assert {row.client for row in report.rows} == {"foghttp", "httpx"}


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_different_modes_remain_distinct_measurements(tmp_path: Path, suite: str) -> None:
    first = ordinary_aggregate(suite)
    path = saved_report(tmp_path, suite, [first, {**first, "mode": "sync"}])

    report = load_benchmark_report(path)

    assert len(report.rows) == ROW_COUNT
    assert report.rows[0].identity != report.rows[1].identity


@pytest.mark.parametrize(
    ("suite", "field", "value"),
    [
        ("requests", "scenario", "second-case"),
        ("requests", "concurrency", 2),
        ("requests", "request_limit", 2),
        ("client-creation", "client_count", 2),
        ("client-creation", "iterations", 5),
        ("resource-backpressure", "per_origin_request_limit", 1),
        ("resource-backpressure", "max_pending_requests", 1),
        ("resource-backpressure", "max_buffered_response_bytes", 4096),
        ("one-upstream", "profile", "direct"),
        ("one-upstream", "group", "second-group"),
        ("request-builder", "profile", "direct"),
        ("request-builder", "kind", "send-prepared"),
        ("request-builder", "iterations", 5),
        ("response-streaming", "case", "second-case"),
        ("response-streaming", "read", "lines"),
        ("response-streaming", "consume", "first-chunk"),
        ("proxy-connect", "group", "second-group"),
        ("proxy-connect", "target_scheme", "http"),
        ("proxy-connect", "config", "explicit"),
        ("proxy-connect", "lifecycle", "cold-client"),
    ],
)
def test_distinct_suite_identity_dimensions_are_not_false_duplicates(
    tmp_path: Path,
    suite: str,
    field: str,
    value: object,
) -> None:
    first = ordinary_aggregate(suite)
    second = {**first, field: value}
    path = saved_report(tmp_path, suite, [first, second])

    report = load_benchmark_report(path)

    assert len(report.rows) == ROW_COUNT
    assert report.rows[0].identity != report.rows[1].identity
