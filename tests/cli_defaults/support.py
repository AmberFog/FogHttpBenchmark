import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import cli
from foghttp_benchmark.application import composition, execution
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    REQUESTS_SUITE,
    RESULTS_DIR,
)
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.proxy_connect import suite as proxy_suite
from foghttp_benchmark.streaming import suite as streaming_suite


def benchmark_args(**overrides: object) -> BenchmarkArgs:
    args = BenchmarkArgs(
        suite=REQUESTS_SUITE,
        clients=DEFAULT_CLIENTS,
        modes=DEFAULT_MODES,
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(RESULTS_DIR),
        scenarios=DEFAULT_SCENARIOS,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
    return replace(args, **overrides)


def invoke_without_work(monkeypatch: pytest.MonkeyPatch, parameters: list[str]) -> BenchmarkArgs:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)

    result = CliRunner().invoke(cli.app, [*parameters, "--no-progress"])

    if result.exit_code != 0:
        pytest.fail(result.output)
    run.assert_awaited_once()
    args = run.await_args.args[0]
    if not isinstance(args, BenchmarkArgs):
        pytest.fail("CLI must pass concrete BenchmarkArgs to execution")
    return args


@asynccontextmanager
async def fake_benchmark_server() -> AsyncIterator[str]:
    yield "http://127.0.0.1:1"


@asynccontextmanager
async def fake_tls_server() -> AsyncIterator[SimpleNamespace]:
    yield SimpleNamespace(base_url="https://127.0.0.1:2", ca_cert_path="test-ca.pem")


@asynccontextmanager
async def fake_proxy_server() -> AsyncIterator[SimpleNamespace]:
    yield SimpleNamespace(url="http://127.0.0.1:3", stats=object())


def capture_streaming_execution(
    monkeypatch: pytest.MonkeyPatch,
    args: BenchmarkArgs,
) -> tuple[dict[str, object], BenchmarkArgs]:
    run = AsyncMock(return_value=[])
    write = Mock()
    monkeypatch.setattr(streaming_suite, "available_streaming_clients", Mock(return_value=([object()], {})))
    monkeypatch.setattr(streaming_suite, "benchmark_server", fake_benchmark_server)
    monkeypatch.setattr(streaming_suite, "run_response_streaming_benchmarks", run)
    monkeypatch.setattr(streaming_suite, "write_streaming_reports", write)

    asyncio.run(composition.run_benchmark_suite(args))

    run.assert_awaited_once()
    write.assert_called_once()
    reported_args = write.call_args.args[2]
    if not isinstance(reported_args, BenchmarkArgs):
        pytest.fail("Streaming report must receive concrete BenchmarkArgs")
    return run.await_args.kwargs, reported_args


def capture_proxy_execution(
    monkeypatch: pytest.MonkeyPatch,
    args: BenchmarkArgs,
) -> tuple[dict[str, object], BenchmarkArgs]:
    run = AsyncMock(return_value=[])
    write = Mock()
    monkeypatch.setattr(proxy_suite, "available_proxy_connect_clients", Mock(return_value=([object()], {})))
    monkeypatch.setattr(proxy_suite, "benchmark_server", fake_benchmark_server)
    monkeypatch.setattr(proxy_suite, "benchmark_tls_server", fake_tls_server)
    monkeypatch.setattr(proxy_suite, "http_proxy_server", fake_proxy_server)
    monkeypatch.setattr(proxy_suite, "run_proxy_connect_benchmarks", run)
    monkeypatch.setattr(proxy_suite, "write_proxy_connect_reports", write)

    asyncio.run(composition.run_benchmark_suite(args))

    run.assert_awaited_once()
    write.assert_called_once()
    reported_args = write.call_args.args[2]
    if not isinstance(reported_args, BenchmarkArgs):
        pytest.fail("Proxy report must receive concrete BenchmarkArgs")
    return run.await_args.kwargs, reported_args
