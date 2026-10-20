from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import _child, cli
from foghttp_benchmark.application import execution
from foghttp_benchmark.models import BenchmarkArgs


PARAMETER_ERROR_EXIT = 2


@pytest.mark.parametrize("show_progress", [False, True])
def test_cli_delegates_effective_arguments_to_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    show_progress: bool,
) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)

    result = CliRunner().invoke(
        cli.app,
        [
            "--clients",
            "httpx",
            "--requests",
            "7",
            "--warmup",
            "0",
            "--output-dir",
            str(tmp_path),
            "--progress" if show_progress else "--no-progress",
        ],
    )

    assert result.exit_code == 0, result.output
    run.assert_awaited_once()
    args = run.await_args.args[0]
    assert isinstance(args, BenchmarkArgs)
    assert (args.clients, args.requests, args.warmup, args.output_dir) == ("httpx", 7, 0, str(tmp_path))
    assert run.await_args.kwargs == {"show_progress": show_progress}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("show_progress", [False, True])
def test_child_entrypoint_delegates_arguments_directly_to_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    show_progress: bool,
) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark_child", run)

    _child.main(
        [
            "--clients",
            "httpx",
            "--requests",
            "7",
            "--warmup",
            "0",
            "--output-dir",
            str(tmp_path),
            "--progress" if show_progress else "--no-progress",
        ],
    )

    run.assert_awaited_once()
    args = run.await_args.args[0]
    assert isinstance(args, BenchmarkArgs)
    assert (args.clients, args.requests, args.warmup, args.output_dir) == ("httpx", 7, 0, str(tmp_path))
    assert run.await_args.kwargs == {"show_progress": show_progress}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_cli_translates_application_parameter_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    run = AsyncMock(side_effect=error_type("fixture parameter failure"))
    monkeypatch.setattr(execution, "run_benchmark", run)

    result = CliRunner().invoke(cli.app, ["--no-progress"])

    assert result.exit_code == PARAMETER_ERROR_EXIT
    assert "fixture parameter failure" in result.output
    run.assert_awaited_once()


@pytest.mark.parametrize("error_type", [TypeError, ValueError])
def test_child_entrypoint_translates_application_parameter_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error_type: type[Exception],
) -> None:
    run = AsyncMock(side_effect=error_type("fixture parameter failure"))
    monkeypatch.setattr(execution, "run_benchmark_child", run)

    with pytest.raises(SystemExit) as observed:
        _child.main(["--clients", "httpx"])

    assert observed.value.code == PARAMETER_ERROR_EXIT
    assert "fixture parameter failure" in capsys.readouterr().err
    run.assert_awaited_once()


def test_cli_keeps_unexpected_application_errors_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RuntimeError("fixture unexpected failure")
    run = AsyncMock(side_effect=error)
    monkeypatch.setattr(execution, "run_benchmark", run)

    result = CliRunner().invoke(cli.app, ["--no-progress"])

    assert result.exit_code == 1
    assert result.exception is error
    run.assert_awaited_once()


def test_child_entrypoint_keeps_unexpected_application_errors_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RuntimeError("fixture unexpected failure")
    run = AsyncMock(side_effect=error)
    monkeypatch.setattr(execution, "run_benchmark_child", run)

    with pytest.raises(RuntimeError) as observed:
        _child.main(["--clients", "httpx"])

    assert observed.value is error
    run.assert_awaited_once()
