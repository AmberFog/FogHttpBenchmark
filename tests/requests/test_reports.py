from dataclasses import asdict

from foghttp_benchmark.models import RunResult
from foghttp_benchmark.reports import aggregate_results


EXPECTED_ERRORS_TOTAL = 7
EXPECTED_WARMUP_ERRORS_TOTAL = 3


def test_request_aggregate_preserves_error_type_totals() -> None:
    rows = aggregate_results(
        [
            run_result(
                repeat=0,
                errors=3,
                warmup_errors=1,
                error_types={"RequestError": 2, "check_failed": 1},
                warmup_error_types={"RequestError": 1},
            ),
            run_result(
                repeat=1,
                errors=4,
                warmup_errors=2,
                error_types={"RequestError": 3, "TimeoutError": 1},
                warmup_error_types={"TimeoutError": 2},
            ),
        ],
    )

    assert len(rows) == 1
    payload = asdict(rows[0])
    assert payload["errors_total"] == EXPECTED_ERRORS_TOTAL
    assert payload["warmup_errors_total"] == EXPECTED_WARMUP_ERRORS_TOTAL
    assert payload["error_types"] == {
        "RequestError": 5,
        "TimeoutError": 1,
        "check_failed": 1,
    }
    assert payload["warmup_error_types"] == {
        "RequestError": 1,
        "TimeoutError": 2,
    }


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
        ok_requests_per_second=95.0,
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
