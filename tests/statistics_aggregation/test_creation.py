from dataclasses import replace

import pytest

from foghttp_benchmark.creation_reports import aggregate_creation_results
from tests.statistics_aggregation.support import (
    EXPECTED_CV_PERCENT,
    EXPECTED_ERROR_TOTAL,
    EXPECTED_PARTIAL_COVERAGE,
    EXPECTED_RATE,
    EXPECTED_RSS_MB,
    EXPECTED_UNAVAILABLE_COVERAGE,
    OBSERVATIONS,
)
from tests.timing.report_cases import creation_result


def test_creation_aggregate_retains_sample_variation_and_nullable_measurements() -> None:
    results = [
        replace(
            creation_result(),
            repeat=item.repeat,
            operations_per_second=item.rate,
            errors=item.errors,
            error_types=item.error_types,
            peak_rss_delta_mb=item.rss_mb,
            end_rss_delta_mb=None,
            close_p50_ms=None if item.repeat == 1 else item.rate,
            close_p95_ms=None,
        )
        for item in OBSERVATIONS
    ]

    [row] = aggregate_creation_results(results)

    assert row.repeats == len(OBSERVATIONS)
    assert row.ops_s_median == EXPECTED_RATE
    assert row.ops_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.peak_rss_delta_mb_max == EXPECTED_RSS_MB
    assert row.end_rss_delta_mb_max is None
    assert row.resource_coverage["peak_rss_delta_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["end_rss_delta_mb_max"] == EXPECTED_UNAVAILABLE_COVERAGE
    assert row.close_p50_ms_median == pytest.approx(25.0)
    assert row.close_p95_ms_median is None
