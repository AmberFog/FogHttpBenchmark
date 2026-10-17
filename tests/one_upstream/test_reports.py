import pytest

from foghttp_benchmark.one_upstream.models import OneUpstreamResult
from foghttp_benchmark.one_upstream.reports import aggregate_one_upstream_results


EXPECTED_WARMUP_ERRORS_TOTAL = 3


def test_aggregate_one_upstream_results_adds_direct_baseline_ratios() -> None:
    rows = aggregate_one_upstream_results(
        [
            one_upstream_result(
                case="direct-get",
                profile="direct",
                ok_requests_per_second=100.0,
            ),
            one_upstream_result(
                case="defaults-get",
                profile="defaults",
                ok_requests_per_second=80.0,
            ),
        ],
    )

    by_case = {row.case: row for row in rows}

    assert by_case["direct-get"].baseline_ratio == pytest.approx(1.0)
    assert by_case["defaults-get"].baseline_ratio == pytest.approx(0.8)


def test_aggregate_one_upstream_results_preserves_warmup_error_types() -> None:
    rows = aggregate_one_upstream_results(
        [
            one_upstream_result(
                case="direct-get",
                profile="direct",
                ok_requests_per_second=100.0,
                warmup_error_types={"RuntimeError": 2},
                warmup_errors=2,
            ),
            one_upstream_result(
                case="direct-get",
                profile="direct",
                ok_requests_per_second=120.0,
                warmup_error_types={"TimeoutError": 1},
                warmup_errors=1,
            ),
        ],
    )

    assert rows[0].warmup_errors_total == EXPECTED_WARMUP_ERRORS_TOTAL
    assert rows[0].warmup_error_types == {
        "RuntimeError": 2,
        "TimeoutError": 1,
    }


def one_upstream_result(
    *,
    case: str,
    profile: str,
    ok_requests_per_second: float,
    warmup_error_types: dict[str, int] | None = None,
    warmup_errors: int = 0,
) -> OneUpstreamResult:
    return OneUpstreamResult(
        case=case,
        client="foghttp",
        concurrency=10,
        duration_s=1.0,
        error_types={},
        errors=0,
        group="get",
        mode="async",
        ok_requests=100,
        ok_requests_per_second=ok_requests_per_second,
        p50_ms=1.0,
        p95_ms=2.0,
        p99_ms=3.0,
        peak_fds=10,
        peak_rss_mb=20.0,
        peak_threads=2,
        client_stats=None,
        profile=profile,
        repeat=1,
        request_limit=10,
        requests=100,
        requests_per_second=ok_requests_per_second,
        warmup_error_types=warmup_error_types or {},
        warmup_errors=warmup_errors,
    )
