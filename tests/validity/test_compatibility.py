import pytest

from foghttp_benchmark.constants import COMPRESSED_RESPONSE_SUITE, REQUESTS_SUITE, RESOURCE_BACKPRESSURE_SUITE
from foghttp_benchmark.validity import classify_report_validity
from tests.validity.factories import compatibility_row


@pytest.mark.parametrize(
    ("suite", "scenario"),
    [
        pytest.param(REQUESTS_SUITE, "json-small", id="requests"),
        pytest.param(COMPRESSED_RESPONSE_SUITE, "gzip-64k", id="compressed"),
    ],
)
def test_warmup_exception_never_exempts_measured_runtime_errors(suite: str, scenario: str) -> None:
    summary = classify_report_validity(
        suite=suite,
        aggregate_rows=[
            compatibility_row(
                scenario=scenario,
                errors_total=100,
                error_types={"RuntimeError": 100},
                ok_req_s_median=0.0,
                ok_requests_total=0,
                warmup_errors_total=5,
                warmup_error_types={"RuntimeError": 5},
            ),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert {reason.code for reason in summary.reasons} >= {
        "unexpected_measured_errors",
        "zero_success_throughput",
    }


@pytest.mark.parametrize("scenario", ["br-64k", "multi-gzip-deflate-64k"])
def test_generic_runtime_error_is_not_a_decode_compatibility_failure(scenario: str) -> None:
    summary = classify_report_validity(
        suite=COMPRESSED_RESPONSE_SUITE,
        aggregate_rows=[
            compatibility_row(
                mode="async",
                scenario=scenario,
                errors_total=1,
                error_types={"RuntimeError": 1},
            ),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert "unexpected_measured_errors" in {reason.code for reason in summary.reasons}


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_known_and_unknown_errors_remain_separate(mode: str) -> None:
    summary = classify_report_validity(
        suite=COMPRESSED_RESPONSE_SUITE,
        aggregate_rows=[
            compatibility_row(
                client="aiohttp",
                mode=mode,
                scenario="multi-gzip-deflate-64k",
                errors_total=2,
                error_types={"check_failed": 1, "RuntimeError": 1},
            ),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert {reason.code for reason in summary.reasons} >= {
        "expected_compatibility_failure",
        "unexpected_measured_errors",
    }


def test_expected_errors_in_one_phase_cannot_cover_the_other_phase() -> None:
    summary = classify_report_validity(
        suite=COMPRESSED_RESPONSE_SUITE,
        aggregate_rows=[
            compatibility_row(
                client="aiohttp",
                scenario="multi-gzip-deflate-64k",
                errors_total=2,
                error_types={"check_failed": 1, "RuntimeError": 1},
                warmup_errors_total=1,
                warmup_error_types={"check_failed": 2},
            ),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert {reason.code for reason in summary.reasons} >= {
        "unexpected_measured_errors",
        "unexpected_warmup_errors",
    }


def test_unknown_resource_warmup_error_is_not_expected_pressure() -> None:
    summary = classify_report_validity(
        suite=RESOURCE_BACKPRESSURE_SUITE,
        aggregate_rows=[
            compatibility_row(
                client="foghttp",
                scenario="pending-queue-full",
                warmup_errors_total=2,
                warmup_error_types={"PoolTimeout": 1, "RuntimeError": 1},
            ),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert "unexpected_warmup_errors" in {reason.code for reason in summary.reasons}


def test_expected_resource_warmup_pressure_remains_valid() -> None:
    summary = classify_report_validity(
        suite=RESOURCE_BACKPRESSURE_SUITE,
        aggregate_rows=[
            compatibility_row(
                client="foghttp",
                scenario="pending-queue-full",
                warmup_errors_total=2,
                warmup_error_types={"PoolTimeout": 2},
            ),
        ],
    )

    assert summary.status == "valid"
    assert summary.can_compare


def test_sync_warmup_rule_does_not_apply_to_async_warmup() -> None:
    summary = classify_report_validity(
        suite=REQUESTS_SUITE,
        aggregate_rows=[
            compatibility_row(mode="async", warmup_errors_total=1, warmup_error_types={"RuntimeError": 1}),
        ],
    )

    assert summary.status == "needs-rerun"
    assert not summary.can_compare
    assert [reason.code for reason in summary.reasons] == ["unexpected_warmup_errors"]
