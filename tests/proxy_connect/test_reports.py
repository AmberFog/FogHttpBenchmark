import json
from pathlib import Path

import pytest

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_REPEATS,
    PROXY_CONNECT_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.proxy_connect.models import ProxyConnectResult, ProxyStatsDelta
from foghttp_benchmark.proxy_connect.reports import (
    aggregate_proxy_connect_results,
    redacted_proxy_url,
    write_proxy_connect_reports,
)


EXPECTED_TOTAL_CONNECTS = 2


def test_aggregate_proxy_connect_results_adds_direct_ratios_and_proxy_counters() -> None:
    rows = aggregate_proxy_connect_results(
        [
            proxy_connect_result(
                case="direct-https",
                config="direct",
                ok_requests_per_second=100.0,
                measured_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
                total_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
            ),
            proxy_connect_result(
                case="proxy-connect",
                config="explicit",
                ok_requests_per_second=70.0,
                measured_proxy=ProxyStatsDelta(0, 1, 0, 100, 200),
                total_proxy=ProxyStatsDelta(0, 2, 0, 300, 400),
            ),
        ],
    )

    by_case = {row.case: row for row in rows}

    assert by_case["direct-https"].direct_ratio == pytest.approx(1.0)
    assert by_case["proxy-connect"].direct_ratio == pytest.approx(0.7)
    assert by_case["proxy-connect"].measured_proxy_connect_requests_max == 1
    assert by_case["proxy-connect"].total_proxy_connect_requests_max == EXPECTED_TOTAL_CONNECTS


def test_redacted_proxy_url_hides_userinfo() -> None:
    userinfo = ("bench-user", "bench-auth")
    proxy_url = f"http://{userinfo[0]}:{userinfo[1]}@127.0.0.1:8080"

    redacted = redacted_proxy_url(proxy_url)

    assert redacted == "http://***:***@127.0.0.1:8080"
    assert userinfo[0] not in redacted
    assert userinfo[1] not in redacted


def test_proxy_connect_report_marks_missing_connect_counter_invalid(tmp_path: Path) -> None:
    userinfo = ("bench-user", "bench-auth")
    write_proxy_connect_reports(
        [
            proxy_connect_result(
                case="proxy-connect",
                config="explicit",
                ok_requests_per_second=100.0,
                measured_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
                total_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
            ),
        ],
        {},
        benchmark_args(tmp_path),
        proxy_url=f"http://{userinfo[0]}:{userinfo[1]}@127.0.0.1:8080",
    )

    payload = json.loads((tmp_path / "latest.json").read_text())
    markdown = (tmp_path / "latest.md").read_text()

    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["validity"]["can_compare"] is False
    assert payload["metadata"]["validity"]["reasons"][0]["code"] == "missing_proxy_connect_counter"
    assert "## Run Validity" in markdown
    assert "missing_proxy_connect_counter" in markdown


def proxy_connect_result(
    *,
    case: str,
    config: str,
    ok_requests_per_second: float,
    measured_proxy: ProxyStatsDelta,
    total_proxy: ProxyStatsDelta,
) -> ProxyConnectResult:
    return ProxyConnectResult(
        case=case,
        client="foghttp",
        client_stats={
            "connections_aborted": 0,
            "connections_closed": 1,
            "connections_opened": 2,
            "connections_reused": 3,
        },
        concurrency=10,
        config=config,
        duration_s=1.0,
        error_types={},
        errors=0,
        group="https",
        lifecycle="reused-client",
        measured_proxy=measured_proxy,
        mode="async",
        ok_requests=100,
        ok_requests_per_second=ok_requests_per_second,
        p50_ms=1.0,
        p95_ms=2.0,
        p99_ms=3.0,
        peak_fds=10,
        peak_rss_mb=20.0,
        peak_threads=2,
        repeat=1,
        request_limit=10,
        requests=100,
        requests_per_second=ok_requests_per_second,
        target_scheme="https",
        total_proxy=total_proxy,
        warmup_error_types={},
        warmup_errors=0,
    )


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=PROXY_CONNECT_SUITE,
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=100,
        warmup=0,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=True,
        output_dir=str(output_dir),
        scenarios="proxy-connect",
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
