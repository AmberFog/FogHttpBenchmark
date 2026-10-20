import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from foghttp_benchmark import suite_selection
from foghttp_benchmark.application import composition
from foghttp_benchmark.models import AsyncClientSpec
from foghttp_benchmark.progress import ProgressReporter
from tests.application.suite_cases import (
    COMMON_CLIENT_SUITES,
    LEAF_WORK,
    SPECIALIZED_REGISTRIES,
    SUITE_ROUTES,
    patch_suite_servers,
)
from tests.cli_defaults.support import benchmark_args


@pytest.mark.parametrize("suite", SUITE_ROUTES)
def test_suite_dispatch_preserves_arguments_and_registry_ownership(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    args = benchmark_args(suite=suite, clients="httpx,foghttp", modes="async,sync", requests=7)
    registry = Mock()
    reporter = MagicMock(spec=ProgressReporter)
    routes = {name: AsyncMock() for name in SUITE_ROUTES}
    monkeypatch.setattr(suite_selection, "available_clients", registry)
    for name, run in routes.items():
        monkeypatch.setitem(composition.SUITES, name, replace(composition.get_suite(name), run=run))

    asyncio.run(composition.run_benchmark_suite(args, progress=reporter))

    for name, run in routes.items():
        if name == suite:
            run.assert_awaited_once_with(args, progress=reporter)
        else:
            run.assert_not_awaited()
    registry.assert_not_called()


@pytest.mark.parametrize("suite", SUITE_ROUTES)
def test_leaf_suite_resolves_clients_and_preserves_skipped_results(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    module, run_name = SUITE_ROUTES[suite]
    work_name, writer_name, scenario = LEAF_WORK[suite]
    args = benchmark_args(
        suite=suite,
        clients="httpx,foghttp",
        modes="async,sync",
        scenarios=scenario,
        concurrency="1",
        requests=7,
        warmup=0,
        iterations=1,
        client_counts="1",
    )
    clients = [AsyncClientSpec("foghttp", Mock())]
    skipped = {"sync:missing": "not installed"}
    registry = Mock(return_value=(clients, skipped))
    owner = suite_selection if suite in COMMON_CLIENT_SUITES else module
    name = "available_clients" if suite in COMMON_CLIENT_SUITES else SPECIALIZED_REGISTRIES[suite]
    monkeypatch.setattr(owner, name, registry)
    patch_suite_servers(monkeypatch, module)
    work = Mock(return_value=[]) if work_name == "build_plan" else AsyncMock(return_value=[])
    write = Mock()
    reporter = MagicMock(spec=ProgressReporter)
    monkeypatch.setattr(module, work_name, work)
    monkeypatch.setattr(module, writer_name, write)

    asyncio.run(getattr(module, run_name)(args, progress=reporter))

    registry.assert_called_once_with(["httpx", "foghttp"], ["async", "sync"])
    if isinstance(work, AsyncMock):
        work.assert_awaited_once()
        assert work.await_args.kwargs["clients"] == clients
        assert work.await_args.kwargs["progress"] is reporter
    else:
        work.assert_called_once()
        assert work.call_args.kwargs["clients"] == clients
    write.assert_called_once()
    assert write.call_args.args[:3] == ([], skipped, args)


@pytest.mark.parametrize("suite", sorted(COMMON_CLIENT_SUITES))
def test_missing_common_clients_fail_before_suite_execution(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    skipped = {"async:missing": "not installed"}
    registry = Mock(return_value=([], skipped))
    server = Mock(side_effect=AssertionError("missing clients must fail before server startup"))
    module, _run_name = SUITE_ROUTES[suite]
    work_name, _writer_name, _scenario = LEAF_WORK[suite]
    work = Mock()
    monkeypatch.setattr(suite_selection, "available_clients", registry)
    monkeypatch.setattr(module, work_name, work)
    monkeypatch.setattr(module, "benchmark_server", server)

    with pytest.raises(ValueError, match="No requested clients are available"):
        asyncio.run(composition.run_benchmark_suite(benchmark_args(suite=suite)))

    registry.assert_called_once_with(
        ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "zapros-pyreqwest"],
        ["async"],
    )
    work.assert_not_called()
    server.assert_not_called()


@pytest.mark.parametrize("suite", SUITE_ROUTES)
def test_composition_binds_leaf_runner_explicitly(suite: str) -> None:
    module, run_name = SUITE_ROUTES[suite]

    assert composition.get_suite(suite).run is getattr(module, run_name)


@pytest.mark.parametrize("suite", SUITE_ROUTES)
def test_parent_selection_preserves_requested_order_duplicates_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    module, _run_name = SUITE_ROUTES[suite]
    args = benchmark_args(suite=suite, clients=" httpx, foghttp, httpx, absent ", modes="async,sync")
    clients = [AsyncClientSpec("foghttp", Mock()), AsyncClientSpec("httpx", Mock())]
    skipped = {"sync:missing": "not installed"}
    registry = Mock(return_value=(clients, skipped))
    owner = suite_selection if suite in COMMON_CLIENT_SUITES - {"resource-backpressure"} else module
    name = "available_clients" if suite in COMMON_CLIENT_SUITES else SPECIALIZED_REGISTRIES[suite]
    monkeypatch.setattr(owner, name, registry)

    selection = composition.get_suite(suite).select_clients(args)

    registry.assert_called_once_with(["httpx", "foghttp", "httpx", "absent"], ["async", "sync"])
    expected_names = ["foghttp"] if suite == "resource-backpressure" else ["httpx", "foghttp", "httpx"]
    expected_skipped = dict(skipped)
    if suite == "resource-backpressure":
        expected_skipped["async:httpx"] = "resource-backpressure suite requires FogHTTP stats"
    assert selection.clients == expected_names
    assert selection.skipped == expected_skipped
    assert skipped == {"sync:missing": "not installed"}
