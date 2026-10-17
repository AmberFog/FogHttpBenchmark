from foghttp_benchmark.models import RunResult


def run_result(
    *,
    repeat: int,
    errors: int,
    warmup_errors: int,
    error_types: dict[str, int],
    warmup_error_types: dict[str, int],
) -> RunResult:
    return RunResult(
        client="foghttp",
        mode="async",
        scenario="post-echo-64k",
        concurrency=10,
        request_limit=10,
        requests=100,
        repeat=repeat,
        duration_s=1.0,
        requests_per_second=100.0,
        ok_requests_per_second=float(100 - errors),
        ok_requests=100 - errors,
        p50_ms=1.0,
        p90_ms=2.0,
        p95_ms=3.0,
        p99_ms=4.0,
        min_ms=0.5,
        max_ms=5.0,
        errors=errors,
        warmup_errors=warmup_errors,
        error_types=error_types,
        warmup_error_types=warmup_error_types,
        process_cpu_s=0.5,
        peak_rss_mb=64.0,
        peak_threads=4,
        peak_fds=8,
        client_stats=None,
    )
