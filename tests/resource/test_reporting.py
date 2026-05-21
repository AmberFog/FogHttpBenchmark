from foghttp_benchmark.models import ResourceBackpressureResult
from foghttp_benchmark.resource.reporting.aggregation import aggregate_resource_results


BUFFERED_RESPONSE_BUDGET = 98_304
BUFFERED_RESPONSE_BUDGET_REJECTIONS = 5


def test_resource_aggregation_includes_buffered_budget_metrics() -> None:
    rows = aggregate_resource_results(
        [
            resource_result(
                peak_buffered_response_bytes=65_536,
                buffered_response_budget_rejections=3,
                buffered_response_bytes=0,
            ),
            resource_result(
                peak_buffered_response_bytes=BUFFERED_RESPONSE_BUDGET,
                buffered_response_budget_rejections=BUFFERED_RESPONSE_BUDGET_REJECTIONS,
                buffered_response_bytes=0,
            ),
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.max_buffered_response_bytes == BUFFERED_RESPONSE_BUDGET
    assert row.peak_buffered_response_bytes_max == BUFFERED_RESPONSE_BUDGET
    assert row.final_buffered_response_budget_rejections_max == BUFFERED_RESPONSE_BUDGET_REJECTIONS
    assert row.final_buffered_response_bytes_max == 0


def resource_result(
    *,
    peak_buffered_response_bytes: int,
    buffered_response_budget_rejections: int,
    buffered_response_bytes: int,
) -> ResourceBackpressureResult:
    return ResourceBackpressureResult(
        client="foghttp",
        mode="async",
        scenario="aggregate-buffered-budget",
        concurrency=10,
        request_limit=10,
        per_origin_request_limit=10,
        max_pending_requests=100,
        max_response_body_size=131_072,
        max_buffered_response_bytes=BUFFERED_RESPONSE_BUDGET,
        pool_timeout_s=5.0,
        requests=20,
        warmup=0,
        repeat=1,
        duration_s=1.0,
        ok_requests=17,
        errors=3,
        warmup_errors=0,
        error_types={"ResponseBodyBudgetExceededError": 3},
        warmup_error_types={},
        p50_ms=1.0,
        p95_ms=2.0,
        p99_ms=3.0,
        peak_rss_mb=60.0,
        peak_threads=3,
        peak_fds=12,
        peak_active_requests=10,
        peak_pending_requests=0,
        peak_buffered_response_bytes=peak_buffered_response_bytes,
        client_stats={
            "buffered_response_budget_rejections": buffered_response_budget_rejections,
            "buffered_response_bytes": buffered_response_bytes,
            "failed_requests": 3,
            "pool_acquire_timeouts": 0,
        },
        recovery_ok=True,
        recovery_error=None,
    )
