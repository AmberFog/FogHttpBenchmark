import pytest

from foghttp_benchmark.request_builder.models import RequestBuilderResult
from foghttp_benchmark.request_builder.reports import aggregate_request_builder_results


def test_aggregate_request_builder_results_adds_absolute_url_baseline_ratios() -> None:
    rows = aggregate_request_builder_results(
        [
            request_builder_result(
                case="absolute-url",
                group="url",
                profile="direct",
                operations_per_second=100_000.0,
            ),
            request_builder_result(
                case="default-params",
                group="query",
                profile="defaults",
                operations_per_second=80_000.0,
            ),
        ],
    )

    by_case = {row.case: row for row in rows}

    assert by_case["absolute-url"].baseline_ratio == pytest.approx(1.0)
    assert by_case["default-params"].baseline_ratio == pytest.approx(0.8)


def request_builder_result(
    *,
    case: str,
    group: str,
    profile: str,
    operations_per_second: float,
) -> RequestBuilderResult:
    return RequestBuilderResult(
        case=case,
        client="foghttp",
        duration_s=1.0,
        error_types={},
        errors=0,
        group=group,
        iterations=1000,
        kind="build",
        mode="async",
        operations_per_second=operations_per_second,
        p50_ms=0.001,
        p95_ms=0.002,
        p99_ms=0.003,
        peak_fds=10,
        peak_rss_mb=20.0,
        peak_threads=2,
        profile=profile,
        repeat=1,
    )
