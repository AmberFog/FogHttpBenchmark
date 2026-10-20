from dataclasses import replace

import pytest

from foghttp_benchmark.request_builder.reports import aggregate_request_builder_results
from tests.request_builder.test_reports import request_builder_result
from tests.statistics_aggregation.support import (
    EXPECTED_CV_PERCENT,
    EXPECTED_ERROR_TOTAL,
    EXPECTED_ERROR_TYPES,
    EXPECTED_PARTIAL_COVERAGE,
    EXPECTED_RATE,
    EXPECTED_RSS_MB,
    EXPECTED_UNAVAILABLE_COVERAGE,
    OBSERVATIONS,
)


def test_builder_aggregate_retains_variation_errors_and_operation_grouping() -> None:
    results = [
        replace(
            request_builder_result(
                case="default-params",
                group="query",
                profile="defaults",
                operations_per_second=item.rate,
            ),
            repeat=item.repeat,
            errors=item.errors,
            error_types=item.error_types,
            peak_rss_mb=item.rss_mb,
            peak_fds=None,
        )
        for item in OBSERVATIONS
    ]
    baseline = request_builder_result(
        case="absolute-url",
        group="url",
        profile="direct",
        operations_per_second=40.0,
    )
    send = replace(baseline, kind="send-prepared", case="send", operations_per_second=100.0)

    rows = aggregate_request_builder_results([send, *results, baseline])
    row = next(row for row in rows if row.case == "default-params")

    assert {(row.kind, row.case) for row in rows} == {
        ("build", "absolute-url"),
        ("build", "default-params"),
        ("send-prepared", "send"),
    }
    assert row.repeats == len(OBSERVATIONS)
    assert row.ops_s_median == EXPECTED_RATE
    assert row.ops_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.baseline_ratio == pytest.approx(0.5)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.fds_max is None
    assert row.resource_coverage["rss_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["fds_max"] == EXPECTED_UNAVAILABLE_COVERAGE
    assert next(row for row in rows if row.kind == "send-prepared").baseline_ratio is None
