import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import NoReturn

import pytest

from foghttp_benchmark import request_suite, suite_selection
from foghttp_benchmark.constants import BENCHMARK_SEED, REQUESTS_SUITE
from foghttp_benchmark.models import AsyncClientSpec, BenchmarkArgs, RunResult, Scenario


def test_request_suite_settles_after_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scenario = Scenario(name="json-small", method="GET", path="/json-small")
    spec = AsyncClientSpec(name="foghttp", factory=lambda _config: raise_unexpected_factory_call())
    server_calls: list[None] = []
    settling_calls: list[dict[str, int] | None] = []
    reported_config: list[object] = []

    @asynccontextmanager
    async def fake_benchmark_server() -> AsyncIterator[str]:
        server_calls.append(None)
        yield "http://127.0.0.1:1"

    async def fake_run_once(**_kwargs: object) -> RunResult:
        return run_result(client_stats={"connections_opened": 300})

    async def fake_settle_after_run(client_stats: dict[str, int] | None, _config: object, **_kwargs: object) -> None:
        settling_calls.append(client_stats)

    def fake_write_reports(
        _results: list[RunResult],
        _skipped: dict[str, str],
        _args: BenchmarkArgs,
        *,
        settling_config: object,
    ) -> None:
        reported_config.append(settling_config)

    monkeypatch.setattr(request_suite, "benchmark_server", fake_benchmark_server)
    monkeypatch.setattr(request_suite, "build_plan", lambda **_kwargs: [(scenario, 1, spec, 1)])
    monkeypatch.setattr(request_suite, "run_once", fake_run_once)
    monkeypatch.setattr(request_suite, "settle_after_run", fake_settle_after_run)
    monkeypatch.setattr(request_suite, "write_reports", fake_write_reports)

    monkeypatch.setattr(suite_selection, "available_clients", lambda _clients, _modes: ([spec], {}))
    args = benchmark_args(tmp_path)

    asyncio.run(request_suite.run_request_suite(args, progress=None))

    assert server_calls == [None]
    assert settling_calls == [{"connections_opened": 300}]
    assert len(reported_config) == 1


def run_result(*, client_stats: dict[str, int] | None) -> RunResult:
    return RunResult(
        client="foghttp",
        mode="async",
        scenario="json-small",
        concurrency=1,
        request_limit=1,
        requests=1,
        repeat=1,
        duration_s=1.0,
        requests_per_second=1.0,
        ok_requests_per_second=1.0,
        ok_requests=1,
        p50_ms=1.0,
        p90_ms=1.0,
        p95_ms=1.0,
        p99_ms=1.0,
        min_ms=1.0,
        max_ms=1.0,
        errors=0,
        warmup_errors=0,
        error_types={},
        warmup_error_types={},
        process_cpu_s=0.1,
        peak_rss_mb=64.0,
        peak_threads=4,
        peak_fds=8,
        client_stats=client_stats,
    )


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=REQUESTS_SUITE,
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=1,
        warmup=0,
        repeats=1,
        max_redirects=20,
        seed=BENCHMARK_SEED,
        no_shuffle=True,
        output_dir=str(output_dir),
        scenarios="json-small",
        iterations=1,
        client_counts="1",
    )


def raise_unexpected_factory_call() -> NoReturn:
    message = "client factory should not be called"
    raise AssertionError(message)
