from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.report_schema.decoding import decode_report_payload, load_report
from tests.resource_metrics.cases import RESOURCE_REPORT_CASES, ResourceReportCase
from tests.resource_metrics.report_actions import (
    report_payload,
    resource_results,
    write_resource_case,
    write_resource_results,
)


OBSERVED_RECORD_COUNT = 2


@pytest.mark.parametrize("corruption", ["denominator", "raw-count"])
def test_readers_reject_resource_cardinality_corruption_without_changing_source(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    corruption: str,
) -> None:
    path = write_resource_case(resource_case, tmp_path, [None, 0])
    payload = report_payload(path)
    metric = resource_case.metrics[0].aggregate
    assert payload["aggregate"][0]["resource_coverage"][metric]["expected"] == OBSERVED_RECORD_COUNT
    assert payload["aggregate"][0]["resource_coverage"][metric]["available"] == 1
    if corruption == "denominator":
        payload["aggregate"][0]["resource_coverage"][metric]["expected"] = 1
    else:
        payload["runs"].pop(0)
    original_payload = deepcopy(payload)
    path.write_text(json.dumps(payload))
    original_file = path.read_bytes()

    with pytest.raises(ValueError, match=re.escape("aggregate[0]")):
        decode_report_payload(payload)
    for loader in (load_report, load_benchmark_report):
        with pytest.raises(ValueError, match=re.escape("aggregate[0]")) as error:
            loader(path)
        assert str(path) in str(error.value)

    assert payload == original_payload
    assert path.read_bytes() == original_file


def test_each_resource_availability_count_is_checked_against_its_raw_field(
    tmp_path: Path,
    resource_case: ResourceReportCase,
) -> None:
    payload = report_payload(write_resource_case(resource_case, tmp_path, [None, 0]))
    for metric in resource_case.metrics:
        corrupt = deepcopy(payload)
        corrupt["aggregate"][0]["resource_coverage"][metric.aggregate]["available"] = 2
        with pytest.raises(ValueError, match=re.escape(metric.aggregate)):
            decode_report_payload(corrupt)


def test_raw_available_values_cannot_be_relabelled_as_missing(
    tmp_path: Path,
    resource_case: ResourceReportCase,
) -> None:
    payload = report_payload(write_resource_case(resource_case, tmp_path, [0, 7]))
    metric = resource_case.metrics[0].aggregate
    coverage = payload["aggregate"][0]["resource_coverage"][metric]
    coverage.update(available=1, unavailable_reasons=["reason-not-recorded"])

    with pytest.raises(ValueError, match=re.escape(metric)):
        decode_report_payload(payload)


def test_resource_cardinality_uses_group_records_instead_of_configured_repeat_target(
    tmp_path: Path,
    resource_case: ResourceReportCase,
) -> None:
    payload = report_payload(write_resource_case(resource_case, tmp_path, [None, 0]))
    payload["metadata"]["args"]["repeats"] = 19

    report = decode_report_payload(payload)

    assert report.aggregate_rows[0]["repeats"] == OBSERVED_RECORD_COUNT
    for metric in resource_case.metrics:
        assert report.aggregate_rows[0][metric.aggregate] == 0
        assert report.aggregate_rows[0]["resource_coverage"][metric.aggregate] == {
            "available": 1,
            "expected": 2,
            "unavailable_reasons": ["reason-not-recorded"],
        }


@pytest.mark.parametrize("dimension", ["client", "workload"])
def test_resource_counts_are_partitioned_by_canonical_group(
    tmp_path: Path,
    resource_case: ResourceReportCase,
    dimension: str,
) -> None:
    first = resource_results(resource_case, [None, 0])
    other = resource_results(resource_case, [0])[0]
    if dimension == "client":
        other = replace(other, client="httpx")
    else:
        field = "scenario" if hasattr(other, "scenario") else "case"
        changes = {field: "second-case"}
        if resource_case.suite == "proxy-connect":
            changes["config"] = "explicit"
        other = replace(other, **changes)
    write_resource_results(resource_case, tmp_path, [first[0], other, first[1]])

    report = load_report(tmp_path / "latest.json")

    assert sorted(row["repeats"] for row in report.aggregate_rows) == [1, 2]
    for row in report.aggregate_rows:
        for metric in resource_case.metrics:
            observation = row["resource_coverage"][metric.aggregate]
            assert observation["expected"] == row["repeats"]
            assert observation["available"] == 1


def test_aggregate_only_legacy_does_not_fabricate_raw_coverage(
    tmp_path: Path,
    resource_case: ResourceReportCase,
) -> None:
    path = write_resource_case(resource_case, tmp_path, [None, 0])
    payload = report_payload(path)
    payload["metadata"].pop("resource_metric_schema_version")
    payload["metadata"].pop("report_schema_version", None)
    payload["aggregate"][0].pop("resource_coverage")
    payload["runs"] = []
    original = deepcopy(payload)
    path.write_text(json.dumps(payload))

    report = load_report(path)
    comparable = load_benchmark_report(path)

    assert "resource_coverage" not in report.aggregate_rows[0]
    assert report.run_rows == []
    assert comparable.aggregate_rows == report.aggregate_rows
    assert payload == original
    assert report_payload(path) == original


def test_recorded_aggregate_only_coverage_still_agrees_with_actual_repeat_count(
    tmp_path: Path,
    resource_case: ResourceReportCase,
) -> None:
    payload = report_payload(write_resource_case(resource_case, tmp_path, [None, 0]))
    payload["runs"] = []
    payload["metadata"].pop("resource_metric_schema_version")
    payload["metadata"].pop("report_schema_version", None)
    decode_report_payload(payload)
    metric = resource_case.metrics[0].aggregate
    payload["aggregate"][0]["resource_coverage"][metric]["expected"] = 1

    with pytest.raises(ValueError, match=re.escape(metric)):
        decode_report_payload(payload)


def test_creation_signed_deltas_remain_available_observations(tmp_path: Path) -> None:
    case = next(case for case in RESOURCE_REPORT_CASES if case.suite == "client-creation")
    payload = report_payload(write_resource_case(case, tmp_path, [-8, -2]))

    report = decode_report_payload(payload)

    for index, metric in enumerate(case.metrics, start=1):
        assert report.aggregate_rows[0][metric.aggregate] == -2 * index
        assert report.aggregate_rows[0]["resource_coverage"][metric.aggregate]["available"] == OBSERVED_RECORD_COUNT
