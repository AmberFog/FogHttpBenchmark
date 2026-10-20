from dataclasses import asdict, replace

import pytest

from foghttp_benchmark.streaming.reports import aggregate_streaming_results
from foghttp_benchmark.validity.classification import classify_report_validity
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
from tests.streaming.factories import streaming_result


EXPECTED_VERIFIED_BYTES = 600


def test_streaming_aggregate_retains_variation_errors_missing_resources_and_verified_bytes() -> None:
    results = [
        replace(
            streaming_result(streams_per_second=item.rate, ok_streams_per_second=item.rate),
            repeat=item.repeat,
            errors=item.errors,
            error_types=item.error_types,
            warmup_errors=item.warmup_errors,
            warmup_error_types=item.warmup_error_types,
            peak_rss_mb=item.rss_mb,
            peak_fds=None,
            first_chunk_p95_ms=None if item.repeat == 1 else item.rate,
            verified_eof_bytes_total=100 * item.repeat,
        )
        for item in OBSERVATIONS
    ]

    [row] = aggregate_streaming_results(results)

    assert row.repeats == len(OBSERVATIONS)
    assert row.streams_s_median == EXPECTED_RATE
    assert row.streams_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert row.errors_total == EXPECTED_ERROR_TOTAL
    assert row.error_types == EXPECTED_ERROR_TYPES
    assert row.warmup_errors_total == EXPECTED_WARMUP_ERROR_TOTAL
    assert row.warmup_error_types == EXPECTED_WARMUP_ERROR_TYPES
    assert row.rss_mb_max == EXPECTED_RSS_MB
    assert row.fds_max is None
    assert row.resource_coverage["rss_mb_max"] == EXPECTED_PARTIAL_COVERAGE
    assert row.resource_coverage["fds_max"] == EXPECTED_UNAVAILABLE_COVERAGE
    assert row.first_chunk_p95_ms_median == pytest.approx(25.0)
    assert row.verified_eof_bytes_total == EXPECTED_VERIFIED_BYTES
    validity = classify_report_validity(suite="response-streaming", aggregate_rows=[asdict(row)])
    assert validity.status == "needs-rerun"
    assert validity.can_compare is False
    assert {reason.code for reason in validity.reasons} == {
        "unexpected_measured_errors",
        "unexpected_warmup_errors",
    }


def test_streaming_variation_and_errors_are_not_mixed_across_timing_scopes() -> None:
    legacy = replace(
        streaming_result(streams_per_second=10.0),
        timing_scope="includes-sampler-teardown-v1",
        errors=2,
        error_types={"LegacyError": 2},
    )
    current = [streaming_result(streams_per_second=item.rate) for item in OBSERVATIONS]

    rows = aggregate_streaming_results([legacy, *current])
    by_scope = {row.timing_scope: row for row in rows}

    assert set(by_scope) == {legacy.timing_scope, current[0].timing_scope}
    assert by_scope[legacy.timing_scope].streams_s_cv_percent == 0.0
    assert by_scope[legacy.timing_scope].error_types == {"LegacyError": 2}
    assert by_scope[current[0].timing_scope].streams_s_cv_percent == pytest.approx(EXPECTED_CV_PERCENT)
    assert by_scope[current[0].timing_scope].errors_total == 0
    assert by_scope[current[0].timing_scope].error_types == {}
