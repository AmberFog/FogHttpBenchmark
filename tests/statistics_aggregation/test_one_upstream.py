from dataclasses import replace

import pytest

from foghttp_benchmark.one_upstream.reports import aggregate_one_upstream_results
from tests.one_upstream.test_reports import one_upstream_result
from tests.statistics_aggregation.support import (
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


def test_one_upstream_aggregate_retains_variation_errors_and_baseline_grouping() -> None:
    results = [
        replace(
            one_upstream_result(case="defaults-get", profile="defaults", ok_requests_per_second=item.rate),
            repeat=item.repeat,
            errors=item.errors,
            error_types=item.error_types,
            warmup_errors=item.warmup_errors,
            warmup_error_types=item.warmup_error_types,
            peak_rss_mb=item.rss_mb,
            peak_fds=None,
        )
        for item in OBSERVATIONS
    ]
    baseline = one_upstream_result(case="direct-get", profile="direct", ok_requests_per_second=40.0)

    direct, row = aggregate_one_upstream_results([*results, baseline])

    assert direct.case == "direct-get"
    assert direct.baseline_ratio == 1.0
    assert direct.req_s_cv_percent == 0.0
    assert row.repeats == len(OBSERVATIONS)
    assert row.req_s_median == EXPECTED_RATE
    assert row.req_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.baseline_ratio == pytest.approx(0.5)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.warmup_errors_total == EXPECTED_WARMUP_ERROR_TOTAL
    assert row.warmup_error_types == EXPECTED_WARMUP_ERROR_TYPES
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.fds_max is None
    assert row.resource_coverage["rss_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["fds_max"] == EXPECTED_UNAVAILABLE_COVERAGE
