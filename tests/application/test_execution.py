import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from foghttp_benchmark.application import composition, execution
from foghttp_benchmark.isolation.models import CHILD_PROCESS_ISOLATION
from foghttp_benchmark.progress import BenchmarkProgress
from tests.cli_defaults.support import benchmark_args


@pytest.mark.parametrize("profile", ["default", "lifecycle", "async-bytes"])
def test_parent_keeps_process_ownership_for_every_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
) -> None:
    preflight = Mock(return_value={"verified": True})
    isolated = AsyncMock()
    lifecycle = AsyncMock()
    direct = AsyncMock()
    monkeypatch.setattr(execution, "research_provenance_from_env", preflight)
    monkeypatch.setattr(execution, "run_isolated_benchmark", isolated)
    monkeypatch.setattr(execution, "run_lifecycle_profile", lifecycle)
    monkeypatch.setattr(composition, "run_benchmark_suite", direct)
    args = benchmark_args(
        suite="response-streaming",
        streaming_profile=profile,
        isolation="none",
        output_dir=str(tmp_path),
    )

    asyncio.run(execution.run_benchmark(args, show_progress=False))

    preflight.assert_called_once_with(check_remote=True)
    selected, unused = (isolated, lifecycle) if profile == "default" else (lifecycle, isolated)
    selected.assert_awaited_once()
    assert selected.await_args.args == (args,)
    if profile == "default":
        definition = composition.get_suite(args.suite)
        assert selected.await_args.kwargs["select_clients"] is definition.select_clients
        assert selected.await_args.kwargs["scenario_names"] is definition.isolation_scenarios
        assert selected.await_args.kwargs["finalizer"] is definition.finalize_report
    reporter = selected.await_args.kwargs["progress"]
    assert isinstance(reporter, BenchmarkProgress)
    assert reporter.enabled is False
    unused.assert_not_awaited()
    direct.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("profile", ["lifecycle", "async-bytes", "unknown"])
def test_child_cannot_bypass_parent_owned_lifecycle_launcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
) -> None:
    preflight = Mock(return_value={"verified": True})
    direct = AsyncMock()
    monkeypatch.setattr(execution, "research_provenance_from_env", preflight)
    monkeypatch.setattr(composition, "run_benchmark_suite", direct)
    args = benchmark_args(streaming_profile=profile, output_dir=str(tmp_path))

    with pytest.raises(ValueError, match="parent-owned process launcher"):
        asyncio.run(execution.run_benchmark_child(args))

    preflight.assert_called_once_with()
    direct.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("show_progress", [False, True])
def test_child_forces_child_metadata_and_preserves_progress_option(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    show_progress: bool,
) -> None:
    preflight = Mock(return_value=None)
    direct = AsyncMock()
    monkeypatch.setattr(execution, "research_provenance_from_env", preflight)
    monkeypatch.setattr(composition, "run_benchmark_suite", direct)
    args = benchmark_args(isolation="none", output_dir=str(tmp_path))

    asyncio.run(execution.run_benchmark_child(args, show_progress=show_progress))

    preflight.assert_called_once_with()
    direct.assert_awaited_once()
    effective = direct.await_args.args[0]
    assert effective.isolation == CHILD_PROCESS_ISOLATION
    assert args.isolation == "none"
    assert effective.output_dir == args.output_dir
    reporter = direct.await_args.kwargs["progress"]
    assert isinstance(reporter, BenchmarkProgress)
    assert reporter.enabled is show_progress
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entrypoint", ["parent", "child"])
@pytest.mark.parametrize("error_type", [TypeError, ValueError, RuntimeError, asyncio.CancelledError])
def test_application_does_not_translate_execution_failures(
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    error_type: type[BaseException],
) -> None:
    error = error_type("fixture execution failure")
    work = AsyncMock(side_effect=error)
    monkeypatch.setattr(execution, "research_provenance_from_env", Mock(return_value=None))
    monkeypatch.setattr(execution, "run_isolated_benchmark", work)
    monkeypatch.setattr(composition, "run_benchmark_suite", work)
    run = execution.run_benchmark if entrypoint == "parent" else execution.run_benchmark_child

    with pytest.raises(error_type) as observed:
        asyncio.run(run(benchmark_args(), show_progress=False))

    assert observed.value is error
    work.assert_awaited_once()


@pytest.mark.parametrize("suite", tuple(composition.SUITES))
@pytest.mark.parametrize("entrypoint", ["parent", "child"])
def test_parent_and_child_use_the_same_suite_definition(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    entrypoint: str,
) -> None:
    run = AsyncMock()
    select = Mock()
    scenarios = Mock()
    finalizer = Mock()
    definition = replace(
        composition.get_suite(suite),
        run=run,
        select_clients=select,
        isolation_scenarios=scenarios,
        finalize_report=finalizer,
    )
    isolated = AsyncMock()
    monkeypatch.setitem(composition.SUITES, suite, definition)
    monkeypatch.setattr(execution, "research_provenance_from_env", Mock(return_value=None))
    monkeypatch.setattr(execution, "run_isolated_benchmark", isolated)
    args = benchmark_args(suite=suite)

    entry = execution.run_benchmark if entrypoint == "parent" else execution.run_benchmark_child
    asyncio.run(entry(args, show_progress=False))

    if entrypoint == "parent":
        isolated.assert_awaited_once()
        assert isolated.await_args.args == (args,)
        assert isolated.await_args.kwargs["select_clients"] is select
        assert isolated.await_args.kwargs["scenario_names"] is scenarios
        assert isolated.await_args.kwargs["finalizer"] is finalizer
        run.assert_not_awaited()
    else:
        run.assert_awaited_once()
        assert run.await_args.args == (replace(args, isolation=CHILD_PROCESS_ISOLATION),)
        isolated.assert_not_awaited()
    select.assert_not_called()
    scenarios.assert_not_called()
    finalizer.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["parent", "child"])
def test_unknown_suite_fails_before_any_benchmark_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entrypoint: str,
) -> None:
    isolated = AsyncMock()
    lifecycle = AsyncMock()
    monkeypatch.setattr(execution, "research_provenance_from_env", Mock(return_value=None))
    monkeypatch.setattr(execution, "run_isolated_benchmark", isolated)
    monkeypatch.setattr(execution, "run_lifecycle_profile", lifecycle)
    monkeypatch.setattr(composition, "SUITES", {})
    args = benchmark_args(suite="unknown", output_dir=str(tmp_path))
    entry = execution.run_benchmark if entrypoint == "parent" else execution.run_benchmark_child

    with pytest.raises(ValueError, match="unknown benchmark suite: unknown"):
        asyncio.run(entry(args, show_progress=False))

    isolated.assert_not_awaited()
    lifecycle.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
