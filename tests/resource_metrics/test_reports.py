from dataclasses import asdict
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from tests.resource_metrics.cases import (
    EXACT_LARGE_RESOURCE_COUNT,
    RESOURCE_REPORT_CASES,
    RESOURCE_SCHEMA_VERSION,
    ResourceField,
    ResourceReportCase,
)
from tests.resource_metrics.report_actions import (
    replace_resource_metric,
    report_payload,
    resource_results,
    write_resource_case,
    write_resource_results,
)


def test_real_writers_preserve_resource_values_and_observation_coverage(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    observations: tuple[int | None, ...],
) -> None:
    path = write_resource_case(resource_case, tmp_path, observations)
    payload = report_payload(path)
    loaded = load_benchmark_report(path)
    row = payload["aggregate"][0]
    available = [value for value in observations if value is not None]

    assert payload["metadata"]["resource_metric_schema_version"] == RESOURCE_SCHEMA_VERSION
    assert loaded.metadata["resource_metric_schema_version"] == RESOURCE_SCHEMA_VERSION
    assert loaded.aggregate_rows == payload["aggregate"]
    assert payload["runs"] == [asdict(result) for result in resource_results(resource_case, observations)]
    assert set(row["resource_coverage"]) == {metric.aggregate for metric in resource_case.metrics}
    for index, metric in enumerate(resource_case.metrics, start=1):
        expected = max(available) * index if available else None
        assert row[metric.aggregate] == expected
        assert row["resource_coverage"][metric.aggregate] == {
            "available": len(available),
            "expected": len(observations),
            "unavailable_reasons": [] if len(available) == len(observations) else ["reason-not-recorded"],
        }
    markdown = (tmp_path / "latest.md").read_text()
    assert "Resource observation coverage" in markdown
    assert f"{len(available)} / {len(observations)}" in markdown
    assert "None" not in markdown
    if not available:
        assert "unavailable" in markdown


@pytest.mark.parametrize(
    ("case", "metric"),
    [(case, metric) for case in RESOURCE_REPORT_CASES for metric in case.metrics],
    ids=[f"{case.suite}-{metric.aggregate}" for case in RESOURCE_REPORT_CASES for metric in case.metrics],
)
@pytest.mark.parametrize("invalid_value", [False, True])
def test_resource_writers_reject_boolean_measurements_before_publication(
    tmp_path: Path,
    case: ResourceReportCase,
    metric: ResourceField,
    *,
    invalid_value: bool,
) -> None:
    results = resource_results(case, [0])
    results[0] = replace_resource_metric(results[0], metric, invalid_value)

    with pytest.raises(TypeError, match=r"resource|Resource|numeric|number|bool"):
        write_resource_results(case, tmp_path, results)

    assert not (tmp_path / "latest.json").exists()


def test_creation_resource_deltas_preserve_negative_measurements(tmp_path: Path) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == "client-creation")
    path = write_resource_case(case, tmp_path, [-8, -2])
    row = report_payload(path)["aggregate"][0]

    for index, metric in enumerate(case.metrics, start=1):
        assert row[metric.aggregate] == -2 * index
        assert row["resource_coverage"][metric.aggregate] == {
            "available": 2,
            "expected": 2,
            "unavailable_reasons": [],
        }


def test_integer_resource_counts_keep_full_precision_in_real_markdown_writer(tmp_path: Path) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == "requests")
    result = resource_results(case, [0])[0]
    for metric in case.metrics:
        if metric.aggregate in {"threads_max", "fds_max"}:
            result = replace_resource_metric(result, metric, EXACT_LARGE_RESOURCE_COUNT)

    write_resource_results(case, tmp_path, [result])

    row = report_payload(tmp_path / "latest.json")["aggregate"][0]
    assert row["threads_max"] == EXACT_LARGE_RESOURCE_COUNT
    assert row["fds_max"] == EXACT_LARGE_RESOURCE_COUNT
    aggregate_markdown = (tmp_path / "latest.md").read_text().split("## Resource observation coverage", maxsplit=1)[0]
    assert f"| {EXACT_LARGE_RESOURCE_COUNT} | {EXACT_LARGE_RESOURCE_COUNT} |" in aggregate_markdown
