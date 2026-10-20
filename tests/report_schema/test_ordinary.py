import re

import pytest

from foghttp_benchmark.report_schema.ordinary import validate_ordinary_rows
from tests.report_schema.ordinary_fixtures import ORDINARY_SUITES, ordinary_aggregate, ordinary_run


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_known_ordinary_layout_accepts_aggregate_and_run(suite: str) -> None:
    validate_ordinary_rows(suite, [ordinary_aggregate(suite)], [ordinary_run(suite)])


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
@pytest.mark.parametrize("field", ["client", "mode", "repeats", "errors_total"])
def test_missing_common_aggregate_fields_are_rejected(suite: str, field: str) -> None:
    row = ordinary_aggregate(suite)
    del row[field]
    with pytest.raises((TypeError, ValueError), match=re.escape(f"aggregate[0].{field}")):
        validate_ordinary_rows(suite, [row], [])


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
@pytest.mark.parametrize("value", [-1, 0.5, True, "1", None])
def test_invalid_error_counts_are_not_coerced(suite: str, value: object) -> None:
    row = ordinary_aggregate(suite)
    row["errors_total"] = value
    with pytest.raises((TypeError, ValueError), match=re.escape("aggregate[0].errors_total")):
        validate_ordinary_rows(suite, [row], [])


@pytest.mark.parametrize("value", [False, "2", float("nan"), float("inf"), float("-inf"), None, -1])
def test_invalid_primary_metrics_are_not_coerced(value: object) -> None:
    row = ordinary_aggregate("requests")
    row["ok_req_s_median"] = value
    with pytest.raises((TypeError, ValueError), match=re.escape("aggregate[0].ok_req_s_median")):
        validate_ordinary_rows("requests", [row], [])


def test_missing_primary_is_not_zero() -> None:
    row = ordinary_aggregate("requests")
    del row["ok_req_s_median"]
    with pytest.raises((TypeError, ValueError), match=re.escape("aggregate[0].ok_req_s_median")):
        validate_ordinary_rows("requests", [row], [])


@pytest.mark.parametrize(
    ("suite", "field"),
    [
        ("requests", "scenario"),
        ("compressed-response", "scenario"),
        ("client-creation", "client_count"),
        ("client-creation", "iterations"),
        ("resource-backpressure", "max_pending_requests"),
        ("resource-backpressure", "per_origin_request_limit"),
        ("resource-backpressure", "max_buffered_response_bytes"),
        ("one-upstream", "profile"),
        ("request-builder", "kind"),
        ("response-streaming", "read"),
        ("response-streaming", "consume"),
        ("proxy-connect", "target_scheme"),
        ("proxy-connect", "lifecycle"),
    ],
)
@pytest.mark.parametrize("collection", ["aggregate", "runs"])
def test_suite_specific_identity_is_required(suite: str, field: str, collection: str) -> None:
    row = ordinary_aggregate(suite) if collection == "aggregate" else ordinary_run(suite)
    del row[field]
    with pytest.raises((TypeError, ValueError), match=re.escape(f"{collection}[0].{field}")):
        validate_ordinary_rows(suite, [row] if collection == "aggregate" else [], [row] if collection == "runs" else [])


@pytest.mark.parametrize("field", ["requests", "warmup_errors_total", "concurrency", "request_limit"])
def test_request_counts_cannot_be_missing(field: str) -> None:
    row = ordinary_aggregate("requests")
    del row[field]
    with pytest.raises((TypeError, ValueError), match=re.escape(f"aggregate[0].{field}")):
        validate_ordinary_rows("requests", [row], [])


@pytest.mark.parametrize("field", ["error_types", "warmup_error_types"])
@pytest.mark.parametrize("value", [{"RequestError": 1}, {"RequestError": True}, {"RequestError": -1}, []])
def test_error_maps_are_strict_and_match_their_totals(field: str, value: object) -> None:
    row = ordinary_aggregate("requests")
    row[field] = value
    with pytest.raises((TypeError, ValueError), match=re.escape(f"aggregate[0].{field}")):
        validate_ordinary_rows("requests", [row], [])


@pytest.mark.parametrize("suite", ["resource-backpressure", "one-upstream", "proxy-connect", "response-streaming"])
def test_aggregate_success_count_must_agree_with_measured_count(suite: str) -> None:
    row = ordinary_aggregate(suite)
    row["requests"] = 5
    with pytest.raises((TypeError, ValueError), match="must equal requests"):
        validate_ordinary_rows(suite, [row], [])


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_measured_errors_cannot_exceed_measured_operations(suite: str) -> None:
    row = ordinary_aggregate(suite)
    row["errors_total"] = 9
    with pytest.raises((TypeError, ValueError), match=re.escape("aggregate[0].errors_total")):
        validate_ordinary_rows(suite, [row], [])


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
@pytest.mark.parametrize("field", ["repeat", "duration_s", "errors"])
def test_missing_required_run_fields_are_rejected(suite: str, field: str) -> None:
    row = ordinary_run(suite)
    del row[field]
    with pytest.raises((TypeError, ValueError), match=re.escape(f"runs[0].{field}")):
        validate_ordinary_rows(suite, [], [row])


@pytest.mark.parametrize(
    "suite",
    ["requests", "compressed-response", "resource-backpressure", "one-upstream", "proxy-connect", "response-streaming"],
)
def test_run_success_count_must_agree_with_requests(suite: str) -> None:
    row = ordinary_run(suite)
    row["requests"] = 5
    with pytest.raises((TypeError, ValueError), match="must equal requests"):
        validate_ordinary_rows(suite, [], [row])


@pytest.mark.parametrize("suite", ["client-creation", "request-builder"])
def test_run_operation_errors_cannot_exceed_iterations(suite: str) -> None:
    row = ordinary_run(suite)
    row["errors"] = 5
    with pytest.raises((TypeError, ValueError), match=re.escape("runs[0].errors")):
        validate_ordinary_rows(suite, [], [row])


@pytest.mark.parametrize("field", ["p95_ms_median", "rss_mb_max", "threads_max", "final_connections_opened_max"])
@pytest.mark.parametrize("value", [True, "1", float("nan"), -1])
def test_optional_numeric_fields_cannot_hide_malformed_values(field: str, value: object) -> None:
    row = ordinary_aggregate("requests")
    row[field] = value
    with pytest.raises((TypeError, ValueError), match=re.escape(f"aggregate[0].{field}")):
        validate_ordinary_rows("requests", [row], [])


def test_nullable_resource_metrics_remain_unavailable() -> None:
    row = ordinary_aggregate("requests")
    row.update(rss_mb_max=None, threads_max=None, fds_max=None)
    validate_ordinary_rows("requests", [row], [])
    assert row["rss_mb_max"] is None


def test_creation_resource_deltas_may_be_negative_or_unavailable() -> None:
    row = ordinary_aggregate("client-creation")
    row.update(peak_rss_delta_mb_max=-1.5, end_threads_delta_max=-1, end_fds_delta_max=None)
    validate_ordinary_rows("client-creation", [row], [])


@pytest.mark.parametrize("value", [True, 0.5, "-1"])
def test_creation_resource_count_deltas_are_strict_integers(value: object) -> None:
    row = ordinary_aggregate("client-creation")
    row["end_threads_delta_max"] = value
    with pytest.raises((TypeError, ValueError), match=re.escape("aggregate[0].end_threads_delta_max")):
        validate_ordinary_rows("client-creation", [row], [])


def test_resource_primary_zero_is_structurally_valid_for_pressure_policy() -> None:
    row = ordinary_aggregate("resource-backpressure")
    row.update(ok_requests_total=0, errors_total=8, error_types={"PoolTimeout": 8})
    validate_ordinary_rows("resource-backpressure", [row], [])


def test_zero_limits_and_zero_based_repeat_are_preserved() -> None:
    row = ordinary_run("resource-backpressure")
    validate_ordinary_rows("resource-backpressure", [], [row])
    assert row["repeat"] == 0
    assert row["max_pending_requests"] == 0
    assert row["request_limit"] == 0


def test_nested_client_statistics_use_strict_counts() -> None:
    row = ordinary_run("requests")
    row["client_stats"] = {"active_requests": False}
    with pytest.raises((TypeError, ValueError), match=re.escape("runs[0].client_stats.active_requests")):
        validate_ordinary_rows("requests", [], [row])
