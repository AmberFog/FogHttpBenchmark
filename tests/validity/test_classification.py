from foghttp_benchmark.constants import PROXY_CONNECT_SUITE, REQUESTS_SUITE, RESOURCE_BACKPRESSURE_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity import classify_report_validity


def test_clean_proxy_connect_rows_are_valid() -> None:
    summary = classify_report_validity(
        suite=PROXY_CONNECT_SUITE,
        aggregate_rows=[
            proxy_row("direct-https", config="direct", measured_connect=0, total_connect=0),
            proxy_row("proxy-connect", config="explicit", measured_connect=1, total_connect=1),
        ],
        metadata={},
    )

    assert summary.status == "valid"
    assert summary.can_compare
    assert summary.reasons == ()


def test_proxy_bypass_error_invalidates_report_with_row_context() -> None:
    summary = classify_report_validity(
        suite=PROXY_CONNECT_SUITE,
        aggregate_rows=[
            proxy_row(
                "proxy-connect",
                config="explicit",
                measured_connect=0,
                total_connect=0,
                error_types={"proxy_connect_bypass": 1},
            ),
        ],
        metadata={},
    )

    assert summary.status == "invalid"
    assert not summary.can_compare
    assert {reason.code for reason in summary.reasons} == {
        "missing_proxy_connect_counter",
        "proxy_usage_guard_failed",
    }
    assert summary.reasons[0].row["case"] == "proxy-connect"


def test_expected_resource_pressure_errors_do_not_invalidate_report() -> None:
    summary = classify_report_validity(
        suite=RESOURCE_BACKPRESSURE_SUITE,
        aggregate_rows=[
            resource_row(
                scenario="pending-queue-full",
                errors_total=100,
                ok_requests_total=0,
                error_types={"PoolTimeout": 100},
            ),
            resource_row(
                scenario="response-body-limit",
                errors_total=100,
                ok_requests_total=0,
                error_types={"ResponseBodyTooLargeError": 100},
            ),
        ],
        metadata={},
    )

    assert summary.status == "valid"
    assert summary.reasons == ()


def test_resource_recovery_failure_needs_rerun() -> None:
    summary = classify_report_validity(
        suite=RESOURCE_BACKPRESSURE_SUITE,
        aggregate_rows=[
            resource_row(
                scenario="pool-timeout-recovery",
                errors_total=10,
                ok_requests_total=90,
                error_types={"PoolTimeout": 10},
                recovery_failures=1,
            ),
        ],
        metadata={},
    )

    assert summary.status == "needs-rerun"
    assert [reason.code for reason in summary.reasons] == ["resource_recovery_failed"]


def test_unexpected_errors_and_zero_success_throughput_need_rerun() -> None:
    summary = classify_report_validity(
        suite=REQUESTS_SUITE,
        aggregate_rows=[
            {
                "mode": "async",
                "client": "foghttp",
                "scenario": "json-small",
                "concurrency": 10,
                "request_limit": 10,
                "ok_req_s_median": 0.0,
                "ok_requests_total": 0,
                "errors_total": 10,
                "warmup_errors_total": 1,
                "error_types": {"ConnectError": 10},
            },
        ],
        metadata={},
    )

    assert summary.status == "needs-rerun"
    assert {reason.code for reason in summary.reasons} == {
        "unexpected_measured_errors",
        "unexpected_warmup_errors",
        "zero_success_throughput",
    }


def test_high_variation_is_warning_only() -> None:
    summary = classify_report_validity(
        suite=REQUESTS_SUITE,
        aggregate_rows=[
            {
                "mode": "async",
                "client": "foghttp",
                "scenario": "json-small",
                "concurrency": 10,
                "request_limit": 10,
                "ok_req_s_median": 100.0,
                "errors_total": 0,
                "warmup_errors_total": 0,
                "req_s_cv_percent": 75.0,
            },
        ],
        metadata={},
    )

    assert summary.status == "warning"
    assert summary.can_compare
    assert [reason.code for reason in summary.reasons] == ["high_variation"]


def proxy_row(
    case: str,
    *,
    config: str,
    measured_connect: int,
    total_connect: int,
    error_types: dict[str, int] | None = None,
) -> JsonObject:
    errors_total = 0 if not error_types else sum(error_types.values())
    return {
        "mode": "async",
        "client": "foghttp",
        "case": case,
        "group": "https",
        "target_scheme": "https",
        "config": config,
        "lifecycle": "reused-client",
        "concurrency": 10,
        "request_limit": 10,
        "ok_requests_total": 100,
        "ok_req_s_median": 100.0,
        "errors_total": errors_total,
        "warmup_errors_total": 0,
        "measured_proxy_http_requests_max": 0,
        "measured_proxy_connect_requests_max": measured_connect,
        "total_proxy_http_requests_max": 0,
        "total_proxy_connect_requests_max": total_connect,
        "error_types": error_types or {},
    }


def resource_row(
    *,
    scenario: str,
    errors_total: int,
    ok_requests_total: int,
    error_types: dict[str, int],
    recovery_failures: int = 0,
) -> JsonObject:
    return {
        "mode": "async",
        "client": "foghttp",
        "scenario": scenario,
        "concurrency": 10,
        "request_limit": 1,
        "max_pending_requests": 10,
        "ok_requests_total": ok_requests_total,
        "errors_total": errors_total,
        "warmup_errors_total": 0,
        "recovery_failures": recovery_failures,
        "error_types": error_types,
    }
