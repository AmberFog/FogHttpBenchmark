from dataclasses import replace

import pytest

from foghttp_benchmark.proxy_connect.models import ProxyStatsDelta
from foghttp_benchmark.proxy_connect.reports import aggregate_proxy_connect_results
from tests.proxy_connect.test_reports import proxy_connect_result
from tests.statistics_aggregation.support import (
    EXPECTED_CV_PERCENT,
    EXPECTED_ERROR_TOTAL,
    EXPECTED_ERROR_TYPES,
    EXPECTED_PARTIAL_COVERAGE,
    EXPECTED_RATE,
    EXPECTED_RSS_MB,
    EXPECTED_UNAVAILABLE_COVERAGE,
    EXPECTED_WARMUP_ERROR_TOTAL,
    OBSERVATIONS,
)


def test_proxy_aggregate_retains_variation_errors_direct_ratio_and_counters() -> None:
    results = [
        replace(
            proxy_connect_result(
                case="proxy-connect",
                config="explicit",
                ok_requests_per_second=item.rate,
                measured_proxy=ProxyStatsDelta(0, item.repeat, 0, 0, 0),
                total_proxy=ProxyStatsDelta(0, item.repeat * 2, 0, 0, 0),
            ),
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
    direct = proxy_connect_result(
        case="direct-https",
        config="direct",
        ok_requests_per_second=40.0,
        measured_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
        total_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
    )

    baseline, row = aggregate_proxy_connect_results([*results, direct])

    assert baseline.config == "direct"
    assert baseline.direct_ratio == 1.0
    assert row.repeats == len(OBSERVATIONS)
    assert row.req_s_median == EXPECTED_RATE
    assert row.req_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.direct_ratio == pytest.approx(0.5)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.warmup_errors_total == EXPECTED_WARMUP_ERROR_TOTAL
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.fds_max is None
    assert row.resource_coverage["rss_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["fds_max"] == EXPECTED_UNAVAILABLE_COVERAGE
    assert row.measured_proxy_connect_requests_max == len(OBSERVATIONS)
    assert row.total_proxy_connect_requests_max == 2 * len(OBSERVATIONS)
