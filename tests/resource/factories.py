from pathlib import Path

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    RESOURCE_BACKPRESSURE_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs, ResourceBackpressureResult


BUFFERED_RESPONSE_BUDGET = 98_304


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=RESOURCE_BACKPRESSURE_SUITE,
        clients="foghttp",
        modes="async",
        concurrency="10",
        requests=20,
        warmup=3,
        repeats=2,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(output_dir),
        scenarios="aggregate-buffered-budget",
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )


def resource_result(
    *,
    peak_buffered_response_bytes: int = 0,
    buffered_response_budget_rejections: int = 0,
    buffered_response_bytes: int = 0,
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
