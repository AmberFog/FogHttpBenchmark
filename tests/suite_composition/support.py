from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from foghttp_benchmark import suite_selection
from foghttp_benchmark.models import AsyncClientSpec, BenchmarkArgs, ClientSpec, SyncClientSpec
from foghttp_benchmark.run_settling import RunSettlingConfig
from tests.suite_composition.cases import SuiteCase


HTTP_URL = "http://127.0.0.1:18001"
SECONDARY_URL = "http://127.0.0.1:18002"
TLS_URL = "https://127.0.0.1:18443"
PROXY_URL = "http://127.0.0.1:18080"
SETTLING = RunSettlingConfig(cooldown_s=0.75, opened_connection_threshold=17)


@dataclass
class SuiteHarness:
    args: BenchmarkArgs
    clients: list[ClientSpec]
    skipped: dict[str, str]
    registry: Mock
    work: AsyncMock
    writer: Mock
    events: list[str]
    results: list[object]
    stats: dict[str, int]
    proxy_stats: object
    settle: AsyncMock | None


def make_args(case: SuiteCase, *, no_shuffle: bool = False, scenarios: str | None = None) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=case.name,
        clients="httpx, foghttp",
        modes="sync, async",
        concurrency="3, 1",
        requests=19,
        warmup=5,
        repeats=2,
        max_redirects=7,
        seed=41,
        no_shuffle=no_shuffle,
        output_dir="unused-suite-contract-output",
        scenarios=case.scenarios if scenarios is None else scenarios,
        iterations=11,
        client_counts="4, 2",
    )


@asynccontextmanager
async def recorded_server(label: str, value: object, events: list[str]) -> AsyncIterator[object]:
    events.append(f"enter:{label}")
    try:
        yield value
    finally:
        events.append(f"exit:{label}")


def prepare_suite(
    monkeypatch: pytest.MonkeyPatch,
    case: SuiteCase,
    *,
    failure: BaseException | None = None,
    no_shuffle: bool = False,
    scenarios: str | None = None,
) -> SuiteHarness:
    events: list[str] = []
    factory = Mock(side_effect=AssertionError("contract tests must not instantiate real clients"))
    clients = [SyncClientSpec("httpx", factory), AsyncClientSpec("foghttp", factory)]
    skipped = {"async:unavailable": "fixture client unavailable"}
    registry = Mock(return_value=(clients, skipped))
    owner = suite_selection if case.registry is None else case.module
    monkeypatch.setattr(owner, case.registry or "available_clients", registry)
    stats = {"connections_opened": 123}
    result = SimpleNamespace(client_stats=stats)
    results = [result]

    async def run(**_kwargs: object) -> object:
        events.append("run")
        if failure is not None:
            raise failure
        return result if case.work == "run_once" else results

    work = AsyncMock(side_effect=run)
    writer = Mock(side_effect=lambda *_args, **_kwargs: events.append("write"))
    monkeypatch.setattr(case.module, case.work, work)
    monkeypatch.setattr(case.module, case.writer, writer)
    urls = iter((HTTP_URL, SECONDARY_URL))

    def server() -> object:
        value = next(urls)
        label = "http" if value == HTTP_URL else "secondary"
        return recorded_server(label, value, events)

    monkeypatch.setattr(case.module, "benchmark_server", server)
    proxy_stats = object()
    if case.name == "proxy-connect":
        tls = SimpleNamespace(base_url=TLS_URL, ca_cert_path="controlled-ca.pem")
        proxy = SimpleNamespace(url=PROXY_URL, stats=proxy_stats)
        monkeypatch.setattr(case.module, "benchmark_tls_server", partial(recorded_server, "tls", tls, events))
        monkeypatch.setattr(case.module, "http_proxy_server", partial(recorded_server, "proxy", proxy, events))
    settle = None
    if hasattr(case.module, "run_settling_config"):
        monkeypatch.setattr(case.module, "run_settling_config", Mock(return_value=SETTLING))
    if case.work == "run_once":
        settle = AsyncMock(side_effect=lambda *_args, **_kwargs: events.append("settle"))
        monkeypatch.setattr(case.module, "settle_after_run", settle)
    return SuiteHarness(
        args=make_args(case, no_shuffle=no_shuffle, scenarios=scenarios),
        clients=clients,
        skipped=skipped,
        registry=registry,
        work=work,
        writer=writer,
        events=events,
        results=results,
        stats=stats,
        proxy_stats=proxy_stats,
        settle=settle,
    )
