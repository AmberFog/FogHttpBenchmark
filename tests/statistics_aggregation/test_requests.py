from dataclasses import asdict, replace

import pytest

from foghttp_benchmark.reports import aggregate_results
from foghttp_benchmark.validity.classification import classify_report_validity
from tests.requests.factories import run_result
from tests.statistics_aggregation.support import (
    EXPECTED_COMPLETE_COVERAGE,
    EXPECTED_CV_PERCENT,
    EXPECTED_ERROR_TOTAL,
    EXPECTED_ERROR_TYPES,
    EXPECTED_PARTIAL_COVERAGE,
    EXPECTED_RATE,
    EXPECTED_RSS_MB,
    EXPECTED_UNAVAILABLE_COVERAGE,
    EXPECTED_WARMUP_ERROR_TOTAL,
    EXPECTED_WARMUP_ERROR_TYPES,
    OBSERVATIONS,
)


EXPECTED_HIGH_CV_PERCENT = 86.60254037844386


@pytest.mark.parametrize(("suite", "scenario"), [("requests", "post-echo-64k"), ("compressed-response", "gzip-64k")])
def test_request_aggregate_retains_sample_variation_errors_and_missing_resources(suite: str, scenario: str) -> None:
    results = [
        replace(
            run_result(
                repeat=item.repeat,
                errors=item.errors,
                warmup_errors=item.warmup_errors,
                error_types=item.error_types,
                warmup_error_types=item.warmup_error_types,
            ),
            scenario=scenario,
            requests_per_second=item.rate,
            ok_requests_per_second=item.rate,
            peak_rss_mb=item.rss_mb,
            peak_threads=0,
            peak_fds=None,
        )
        for item in OBSERVATIONS
    ]

    [row] = aggregate_results(results)

    assert row.scenario == scenario
    assert row.repeats == len(OBSERVATIONS)
    assert row.req_s_median == EXPECTED_RATE
    assert row.req_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.warmup_errors_total == EXPECTED_WARMUP_ERROR_TOTAL
    assert row.warmup_error_types == EXPECTED_WARMUP_ERROR_TYPES
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.threads_max == 0
    assert row.fds_max is None
    assert row.resource_coverage == {
        "rss_mb_max": EXPECTED_PARTIAL_COVERAGE,
        "threads_max": EXPECTED_COMPLETE_COVERAGE,
        "fds_max": EXPECTED_UNAVAILABLE_COVERAGE,
    }
    validity = classify_report_validity(suite=suite, aggregate_rows=[asdict(row)])
    assert validity.status == "needs-rerun"
    assert validity.can_compare is False
    assert {reason.code for reason in validity.reasons} == {
        "unexpected_measured_errors",
        "unexpected_warmup_errors",
    }


def test_sample_variation_above_the_threshold_retains_validity_warning() -> None:
    results = [
        replace(
            run_result(repeat=index, errors=0, warmup_errors=0, error_types={}, warmup_error_types={}),
            requests_per_second=rate,
            ok_requests_per_second=rate,
        )
        for index, rate in enumerate((1.0, 1.0, 4.0), start=1)
    ]

    [row] = aggregate_results(results)
    validity = classify_report_validity(suite="requests", aggregate_rows=[asdict(row)])

    assert row.req_s_cv_percent == pytest.approx(EXPECTED_HIGH_CV_PERCENT)
    assert validity.status == "warning"
    assert validity.can_compare is True
    assert [reason.code for reason in validity.reasons] == ["high_variation"]
