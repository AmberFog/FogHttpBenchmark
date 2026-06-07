from dataclasses import dataclass

from pytest import MonkeyPatch

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
)
from foghttp_benchmark.isolation import selection
from foghttp_benchmark.models import BenchmarkArgs


@dataclass(frozen=True)
class FakeClientSpec:
    name: str
    mode: str


def test_proxy_connect_isolation_selection_filters_unsupported_clients(monkeypatch: MonkeyPatch) -> None:
    def fake_available_proxy_connect_clients(
        requested_clients: list[str],
        requested_modes: list[str],
    ) -> tuple[list[FakeClientSpec], dict[str, str]]:
        assert requested_clients == ["foghttp", "httpx", "aiohttp"]
        assert requested_modes == ["async", "sync"]
        return (
            [
                FakeClientSpec(name="foghttp", mode="async"),
                FakeClientSpec(name="foghttp", mode="sync"),
                FakeClientSpec(name="httpx", mode="async"),
            ],
            {"async:aiohttp": "proxy-connect suite requires comparable client-level proxy support"},
        )

    monkeypatch.setattr(selection, "available_proxy_connect_clients", fake_available_proxy_connect_clients)

    result = selection.select_clients_for_isolation(
        BenchmarkArgs(
            suite=PROXY_CONNECT_SUITE,
            clients="foghttp,httpx,aiohttp",
            modes="async,sync",
            concurrency=DEFAULT_CONCURRENCY,
            requests=DEFAULT_REQUESTS,
            warmup=DEFAULT_WARMUP,
            repeats=DEFAULT_REPEATS,
            max_redirects=DEFAULT_MAX_REDIRECTS,
            seed=BENCHMARK_SEED,
            no_shuffle=False,
            output_dir="results",
            scenarios=DEFAULT_SCENARIOS,
            iterations=DEFAULT_CREATION_ITERATIONS,
            client_counts=DEFAULT_CLIENT_COUNTS,
            isolation="per-client",
        ),
    )

    assert result.clients == ["foghttp", "httpx"]
    assert result.skipped == {"async:aiohttp": "proxy-connect suite requires comparable client-level proxy support"}
