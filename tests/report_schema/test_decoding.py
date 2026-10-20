from collections.abc import Callable
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.report_schema.decoding import decode_report_payload, load_report
from foghttp_benchmark.resource.reporting.reports import write_resource_reports
from foghttp_benchmark.resource_metrics import ResourceMetricCoverage
from tests.report_schema.decoding_fixtures import (
    child_process_result,
    payload_metadata,
    payload_rows,
    report_payload,
    write_payload,
)
from tests.report_schema.ordinary_fixtures import ordinary_aggregate
from tests.resource.factories import benchmark_args, resource_result
from tests.timing.report_cases import REPORT_CASES


@pytest.mark.parametrize(("suite", "scope", "writer"), REPORT_CASES)
def test_all_actual_ordinary_writers_round_trip_without_data_loss(
    tmp_path: Path,
    suite: str,
    scope: str,
    writer: Callable[[BenchmarkArgs], None],
) -> None:
    writer(replace(benchmark_args(tmp_path), suite=suite))
    path = tmp_path / "latest.json"
    original = json.loads(path.read_text())

    decoded = load_report(path)
    compared = load_benchmark_report(path)

    assert decoded.suite == compared.suite == suite
    assert decoded.metadata == original["metadata"]
    assert decoded.aggregate_rows == original["aggregate"]
    assert decoded.run_rows == original["runs"]
    assert compared.metadata["timing_scope"] == scope
    assert compared.rows


@pytest.mark.parametrize("legacy", [False, True])
def test_resource_readers_reject_missing_buffer_limit_instead_of_assuming_no_limit(
    tmp_path: Path,
    *,
    legacy: bool,
) -> None:
    write_resource_reports([resource_result()], {}, benchmark_args(tmp_path))
    path = tmp_path / "latest.json"
    payload = json.loads(path.read_text())
    if legacy:
        del payload["metadata"]["report_schema_version"]
    for collection in ("aggregate", "runs"):
        del payload[collection][0]["max_buffered_response_bytes"]
    path.write_text(json.dumps(payload))
    original = path.read_bytes()

    for loader in (load_report, load_benchmark_report):
        with pytest.raises(ValueError, match=r"aggregate\[0\]\.max_buffered_response_bytes"):
            loader(path)

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "suite",
    [
        "requests",
        "client-creation",
        "resource-backpressure",
        "one-upstream",
        "request-builder",
        "response-streaming",
        "proxy-connect",
    ],
)
def test_supported_unambiguous_legacy_suite_inference(suite: str) -> None:
    payload = report_payload(suite)
    del payload_metadata(payload)["suite"]

    decoded = decode_report_payload(payload)

    assert decoded.suite == suite
    assert decoded.metadata["suite"] == suite
    assert "suite" not in payload_metadata(payload)


def test_legacy_request_limit_alias_is_migrated_without_mutating_source() -> None:
    payload = report_payload()
    for collection in ("aggregate", "runs"):
        row = payload_rows(payload, collection)[0]
        row["max_connections"] = row.pop("request_limit")

    decoded = decode_report_payload(payload)

    assert decoded.aggregate_rows[0]["request_limit"] == 0
    assert decoded.run_rows[0]["request_limit"] == 0
    assert "request_limit" not in payload_rows(payload)[0]
    assert "request_limit" not in payload_rows(payload, "runs")[0]


def test_legacy_streaming_read_defaults_to_bytes_without_mutating_source() -> None:
    payload = report_payload("response-streaming")
    for collection in ("aggregate", "runs"):
        del payload_rows(payload, collection)[0]["read"]

    decoded = decode_report_payload(payload)

    assert decoded.aggregate_rows[0]["read"] == "bytes"
    assert decoded.run_rows[0]["read"] == "bytes"
    assert "read" not in payload_rows(payload)[0]


def test_conflicting_legacy_request_limit_is_rejected() -> None:
    payload = report_payload()
    payload_rows(payload)[0]["max_connections"] = 1

    with pytest.raises(ValueError, match=r"aggregate\[0\]\.request_limit disagrees"):
        decode_report_payload(payload)


def test_versioned_layout_cannot_infer_a_missing_suite() -> None:
    payload = report_payload()
    metadata = payload_metadata(payload)
    metadata["report_schema_version"] = 1
    del metadata["suite"]

    with pytest.raises(ValueError, match=r"metadata\.suite is required by report_schema_version"):
        decode_report_payload(payload)


@pytest.mark.parametrize("collection", ["aggregate", "runs"])
def test_versioned_layout_cannot_repair_missing_request_limit_from_alias(collection: str) -> None:
    payload = report_payload()
    payload_metadata(payload)["report_schema_version"] = 1
    row = payload_rows(payload, collection)[0]
    row["max_connections"] = row.pop("request_limit")

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].request_limit")):
        decode_report_payload(payload)


@pytest.mark.parametrize("collection", ["aggregate", "runs"])
def test_versioned_layout_cannot_repair_missing_streaming_read(collection: str) -> None:
    payload = report_payload("response-streaming")
    payload_metadata(payload)["report_schema_version"] = 1
    del payload_rows(payload, collection)[0]["read"]

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].read")):
        decode_report_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("suite", "unknown"),
        ("suite", True),
        ("report_schema_version", 999),
        ("report_schema_version", True),
        ("resource_metric_schema_version", 999),
        ("streaming_metric_schema_version", 2),
        ("schema_version", 1),
    ],
)
def test_unknown_or_misplaced_metadata_versions_and_suite_fail(field: str, value: object) -> None:
    payload = report_payload()
    payload_metadata(payload)[field] = value

    with pytest.raises((TypeError, ValueError), match=re.escape(f"metadata.{field}")):
        decode_report_payload(payload)


@pytest.mark.parametrize("profile", ["unknown", "async-bytes"])
def test_nonstreaming_metadata_cannot_declare_a_streaming_profile(profile: str) -> None:
    payload = report_payload()
    payload_metadata(payload)["profile"] = profile

    with pytest.raises(ValueError, match=r"metadata\.profile"):
        decode_report_payload(payload)


def test_ordinary_streaming_cannot_claim_an_unknown_research_schema() -> None:
    payload = report_payload("response-streaming")
    payload_metadata(payload).update(profile="default", schema_version=999)

    with pytest.raises(ValueError, match=r"metadata\.schema_version"):
        decode_report_payload(payload)


def test_argument_suite_cannot_disagree_with_report_suite() -> None:
    payload = report_payload()
    payload_metadata(payload)["args"] = {"suite": "client-creation"}

    with pytest.raises(ValueError, match=r"metadata\.args\.suite disagrees"):
        decode_report_payload(payload)


def test_parent_requires_child_to_match_its_requested_suite() -> None:
    with pytest.raises(ValueError, match="does not match parent suite"):
        decode_report_payload(report_payload(), expected_suite="client-creation")


def test_missing_suite_cannot_guess_mixed_legacy_layouts() -> None:
    payload = report_payload()
    del payload_metadata(payload)["suite"]
    payload_rows(payload).append(ordinary_aggregate("client-creation"))

    with pytest.raises(ValueError, match="mixed or ambiguous"):
        decode_report_payload(payload)


def test_missing_suite_cannot_guess_an_ambiguous_legacy_row() -> None:
    payload = report_payload()
    del payload_metadata(payload)["suite"]
    payload_rows(payload)[0].update(client_count=1, ops_s_median=1.0)

    with pytest.raises(ValueError, match="ambiguous legacy row"):
        decode_report_payload(payload)


@pytest.mark.parametrize("collection", ["aggregate", "runs"])
def test_explicit_suite_does_not_admit_a_mixed_layout(collection: str) -> None:
    payload = report_payload()
    row = payload_rows(payload, collection)[0]
    row["kind"] = "build"
    row["ops_s_median" if collection == "aggregate" else "operations_per_second"] = 1.0

    with pytest.raises(ValueError, match="layout"):
        decode_report_payload(payload)


@pytest.mark.parametrize("collection", ["aggregate", "runs"])
def test_ordinary_streaming_cannot_declare_a_research_row_schema(collection: str) -> None:
    payload = report_payload("response-streaming")
    payload_metadata(payload)["report_schema_version"] = 1
    payload_rows(payload, collection)[0]["schema_version"] = 999

    with pytest.raises(ValueError, match=re.escape(f"{collection}[0].schema_version")):
        decode_report_payload(payload)


def test_request_run_cannot_include_a_complete_creation_layout() -> None:
    payload = report_payload()
    payload_rows(payload, "runs")[0].update(client_count=1, iterations=4, operations_per_second=4.0)

    with pytest.raises(ValueError, match=r"runs\[0\].*layout"):
        decode_report_payload(payload)


@pytest.mark.parametrize("field", ["metadata", "aggregate", "runs"])
def test_saved_report_requires_its_envelope_fields(field: str) -> None:
    payload = report_payload()
    del payload[field]

    with pytest.raises((TypeError, ValueError), match=field):
        decode_report_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("metadata", []), ("aggregate", {}), ("runs", {}), ("aggregate", [None]), ("runs", [None])],
)
def test_saved_report_rejects_malformed_envelope(field: str, value: object) -> None:
    payload = report_payload()
    payload[field] = value

    with pytest.raises((TypeError, ValueError), match=field):
        decode_report_payload(payload)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_anywhere_is_rejected_with_source_path(tmp_path: Path, number: float) -> None:
    payload = report_payload()
    payload_metadata(payload)["diagnostic"] = {"unexpected_metric": number}
    path = write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match=re.escape(f"{path}: report.metadata.diagnostic.unexpected_metric")):
        load_report(path)


@pytest.mark.parametrize(
    "validity",
    [None, [], {"status": "unknown", "reasons": []}, {"status": "valid", "can_compare": "true", "reasons": []}],
)
def test_malformed_recorded_validity_is_rejected_at_report_boundary(validity: object) -> None:
    payload = report_payload()
    payload_metadata(payload)["validity"] = validity

    with pytest.raises((TypeError, ValueError), match=r"metadata\.validity"):
        decode_report_payload(payload)


@pytest.mark.parametrize("returncode", ["failed", False, 0.5])
def test_saved_child_return_code_cannot_be_coerced_into_success(returncode: object) -> None:
    payload = report_payload()
    payload_metadata(payload)["isolation"] = {
        "children": [{"returncode": returncode, "report_path": "child/latest.json"}],
    }

    with pytest.raises((TypeError, ValueError), match=r"metadata\.isolation\.children\[0\]\.returncode"):
        decode_report_payload(payload)


@pytest.mark.parametrize("profile", ["unknown", "lifecycle", "async-bytes"])
def test_profile_mismatch_is_kept_as_policy_failure(tmp_path: Path, profile: str) -> None:
    payload = report_payload("response-streaming")
    payload_metadata(payload)["profile"] = profile
    payload_rows(payload)[0]["request_limit"] = 1
    path = write_payload(tmp_path, payload)

    report = load_benchmark_report(path)

    assert report.validity.status == "invalid"
    assert report.validity.can_compare is False
    assert "streaming_profile_mismatch" in {reason.code for reason in report.validity.reasons}


def test_nullable_resource_coverage_is_preserved_in_decoding_and_comparison(tmp_path: Path) -> None:
    payload = report_payload()
    row = payload_rows(payload)[0]
    row.update(
        rss_mb_max=None,
        resource_coverage={"rss_mb_max": {"available": 0, "expected": 2, "unavailable_reasons": ["AccessDenied"]}},
    )
    runs = payload_rows(payload, "runs")
    runs[0]["peak_rss_mb"] = None
    runs.append({**runs[0], "repeat": 1})
    payload_metadata(payload)["resource_metric_schema_version"] = 2
    path = write_payload(tmp_path, payload)

    decoded = load_report(path)
    report = load_benchmark_report(path)

    assert decoded.aggregate_rows[0]["resource_coverage"] == row["resource_coverage"]
    assert decoded.aggregate_rows[0]["rss_mb_max"] is None
    assert report.rows[0].rss_mb is None
    assert report.rows[0].resource_coverage["rss_mb_max"] == ResourceMetricCoverage(0, 2, ("AccessDenied",))


@pytest.mark.parametrize("status", ["needs-rerun", "invalid"])
def test_parent_merge_preserves_recorded_child_verdict(tmp_path: Path, status: str) -> None:
    payload = report_payload()
    payload_metadata(payload)["validity"] = {
        "status": status,
        "reasons": [{"status": status, "code": "prior_host_failure"}],
    }
    child_path = write_payload(tmp_path / "child", payload)
    parent_dir = tmp_path / "parent"

    write_isolation_report(
        replace(benchmark_args(parent_dir), suite="requests", isolation="per-client"),
        [child_process_result(child_path)],
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=0.0,
    )

    parent = load_benchmark_report(parent_dir / "latest.json")
    assert parent.validity.status == status
    assert parent.validity.can_compare is False
    assert [reason.code for reason in parent.validity.reasons] == ["prior_host_failure"]


def test_parent_merge_preserves_child_comparison_restriction_without_reasons(tmp_path: Path) -> None:
    payload = report_payload()
    payload_metadata(payload)["validity"] = {"status": "valid", "can_compare": False, "reasons": []}
    child_path = write_payload(tmp_path / "child", payload)
    parent_dir = tmp_path / "parent"

    write_isolation_report(
        replace(benchmark_args(parent_dir), suite="requests", isolation="per-client"),
        [child_process_result(child_path)],
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=0.0,
    )

    parent = load_benchmark_report(parent_dir / "latest.json")
    assert parent.validity.status == "valid"
    assert parent.validity.can_compare is False


@pytest.mark.parametrize("status", ["valid", "needs-rerun", "invalid"])
def test_saved_parent_success_cannot_override_recorded_child_restrictions(tmp_path: Path, status: str) -> None:
    payload = report_payload()
    metadata = payload_metadata(payload)
    metadata["validity"] = {"status": "valid", "can_compare": True, "reasons": []}
    metadata["isolation"] = {
        "children": [
            {
                "returncode": 0,
                "report_path": "child/latest.json",
                "validity": {"status": status, "can_compare": False, "reasons": []},
            },
        ],
    }

    report = load_benchmark_report(write_payload(tmp_path, payload))

    assert report.validity.status == status
    assert report.validity.can_compare is False


def test_malformed_child_is_rejected_before_parent_report_publication(tmp_path: Path) -> None:
    payload = report_payload()
    del payload_rows(payload)[0]["ok_req_s_median"]
    child_path = write_payload(tmp_path / "child", payload)
    child_bytes = child_path.read_bytes()
    result = child_process_result(child_path)
    parent_dir = tmp_path / "parent"

    with pytest.raises(ValueError, match=re.escape(f"{child_path}: aggregate[0].ok_req_s_median")):
        write_isolation_report(
            replace(benchmark_args(parent_dir), suite="requests", isolation="per-client"),
            [result],
            {},
            finalizer=get_suite("requests").finalize_report,
            child_cooldown_s=0.0,
        )

    assert not (parent_dir / "latest.json").exists()
    assert child_path.read_bytes() == child_bytes
    assert result.stderr_tail == "child diagnostics retained"
