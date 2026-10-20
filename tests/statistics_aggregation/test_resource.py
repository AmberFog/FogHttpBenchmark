from dataclasses import asdict, replace

import pytest

from foghttp_benchmark.resource.reporting.aggregation import aggregate_resource_results
from foghttp_benchmark.validity.classification import classify_report_validity
from tests.resource.factories import resource_result
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


FAILED_RECOVERY_REPEAT = 2


def test_resource_aggregate_retains_duration_variation_errors_and_recovery_failure() -> None:
    results = [
        replace(
            resource_result(),
            repeat=item.repeat,
            duration_s=item.rate,
            errors=item.errors,
            ok_requests=20 - item.errors,
            error_types=item.error_types,
            warmup_errors=item.warmup_errors,
            warmup_error_types=item.warmup_error_types,
            peak_rss_mb=item.rss_mb,
            peak_fds=None,
            recovery_ok=item.repeat != FAILED_RECOVERY_REPEAT,
            recovery_error="recovery failed" if item.repeat == FAILED_RECOVERY_REPEAT else None,
        )
        for item in OBSERVATIONS
    ]

    [row] = aggregate_resource_results(results)

    assert row.repeats == len(OBSERVATIONS)
    assert row.duration_s_median == EXPECTED_RATE
    assert row.duration_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.warmup_errors_total == EXPECTED_WARMUP_ERROR_TOTAL
    assert row.warmup_error_types == EXPECTED_WARMUP_ERROR_TYPES
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.fds_max is None
    assert row.resource_coverage["rss_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["fds_max"] == EXPECTED_UNAVAILABLE_COVERAGE
    assert row.recovery_failures == 1
    validity = classify_report_validity(suite="resource-backpressure", aggregate_rows=[asdict(row)])
    assert validity.can_compare is False
    assert "resource_recovery_failed" in {reason.code for reason in validity.reasons}
