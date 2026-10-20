import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from tests.suite_composition.cases import SUITES, SuiteCase
from tests.suite_composition.support import HTTP_URL, prepare_suite, recorded_server


@pytest.mark.parametrize("case", SUITES, ids=lambda case: case.name)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_leaf_suite_closes_servers_before_reporting_and_propagates_failures(
    monkeypatch: pytest.MonkeyPatch,
    case: SuiteCase,
    outcome: str,
) -> None:
    failure = RuntimeError("injected workload failure") if outcome == "error" else None
    harness = prepare_suite(monkeypatch, case, failure=failure)

    async def cancel_at_work(**_kwargs: object) -> None:
        harness.events.append("run")
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)

    if outcome == "cancel":
        harness.work.side_effect = cancel_at_work
    run = getattr(case.module, case.runner)
    if outcome == "success":
        asyncio.run(run(harness.args))
    elif outcome == "error":
        with pytest.raises(RuntimeError, match="injected workload failure") as caught:
            asyncio.run(run(harness.args))
        assert caught.value is failure
    else:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run(harness.args))

    enter_events = [f"enter:{name}" for name in case.servers]
    exit_events = [f"exit:{name}" for name in reversed(case.servers)]
    assert harness.events[: len(enter_events)] == enter_events
    if outcome == "success":
        assert harness.events[-len(exit_events) - 1 :] == [*exit_events, "write"]
        harness.writer.assert_called_once()
    else:
        assert harness.events == [*enter_events, "run", *exit_events]
        harness.writer.assert_not_called()
        if harness.settle is not None:
            harness.settle.assert_not_awaited()
    harness.registry.assert_called_once_with(["httpx", "foghttp"], ["sync", "async"])


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_pure_request_builder_never_starts_server(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    case = next(case for case in SUITES if case.name == "request-builder")
    failure = None
    if outcome == "error":
        failure = RuntimeError("builder failed")
    elif outcome == "cancel":
        failure = asyncio.CancelledError()
    harness = prepare_suite(monkeypatch, case, scenarios="base-url,absolute-url", failure=failure)
    run = getattr(case.module, case.runner)
    if failure is None:
        asyncio.run(run(harness.args))
        assert harness.events == ["run", "write"]
    else:
        with pytest.raises(type(failure)) as caught:
            asyncio.run(run(harness.args))
        assert caught.value is failure
        assert harness.events == ["run"]
        harness.writer.assert_not_called()
    assert harness.work.await_args.kwargs["base_url"] == "http://127.0.0.1:1"
    assert [case.name for case in harness.work.await_args.kwargs["cases"]] == ["base-url", "absolute-url"]


@pytest.mark.parametrize(
    ("suite", "failed_server", "entered"),
    [
        ("resource-backpressure", "secondary", ("http",)),
        ("proxy-connect", "tls", ("http",)),
        ("proxy-connect", "proxy", ("http", "tls")),
    ],
)
def test_partial_server_startup_unwinds_entered_servers_without_work_or_report(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    failed_server: str,
    entered: tuple[str, ...],
) -> None:
    case = next(case for case in SUITES if case.name == suite)
    harness = prepare_suite(monkeypatch, case)
    failure = RuntimeError("server startup failed")

    async def fail_start() -> None:
        harness.events.append(f"start:{failed_server}")
        raise failure

    failed_context = MagicMock()
    failed_context.__aenter__ = AsyncMock(side_effect=fail_start)
    failed_context.__aexit__ = AsyncMock()
    if suite == "resource-backpressure":
        factory = Mock(side_effect=[recorded_server("http", HTTP_URL, harness.events), failed_context])
        monkeypatch.setattr(case.module, "benchmark_server", factory)
    else:
        factory_name = "benchmark_tls_server" if failed_server == "tls" else "http_proxy_server"
        monkeypatch.setattr(case.module, factory_name, Mock(return_value=failed_context))

    with pytest.raises(RuntimeError, match="server startup failed") as caught:
        asyncio.run(getattr(case.module, case.runner)(harness.args))

    assert caught.value is failure
    assert harness.events == [
        *[f"enter:{name}" for name in entered],
        f"start:{failed_server}",
        *[f"exit:{name}" for name in reversed(entered)],
    ]
    failed_context.__aexit__.assert_not_awaited()
    harness.work.assert_not_awaited()
    harness.writer.assert_not_called()
