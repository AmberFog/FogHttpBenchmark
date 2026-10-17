import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import cli
from foghttp_benchmark.streaming import lifecycle
from foghttp_benchmark.streaming.lifecycle_models import (
    LifecycleCase,
    LifecycleConfig,
    validate_lifecycle_case,
    validate_lifecycle_config,
)
from tests.streaming.lifecycle_profile_factory import lifecycle_args, lifecycle_plan


EXPECTED_CASES = 48


def test_lifecycle_profile_has_bounded_reproducible_case_order() -> None:
    first = lifecycle_plan()

    assert len(first) == EXPECTED_CASES
    assert first == lifecycle_plan()
    assert first != lifecycle_plan(seed=43)
    assert {case.repeat for case in first} == {1, 2, 3}
    assert {case.concurrency for case in first} == {1, 10}
    assert {case.case for case in first} == {"first-chunk-close-1m", "stream-1m"}
    assert len({(c.mode, c.client, c.case, c.concurrency, c.repeat) for c in first}) == len(first)


@pytest.mark.parametrize(
    "overrides",
    [
        {"clients": ["aiohttp"]},
        {"modes": ["thread"]},
        {"cases": ["lines-10k"]},
        {"concurrency_levels": [100]},
        {"repeats": 4},
        {"clients": []},
    ],
)
def test_lifecycle_plan_rejects_unsupported_or_excessive_work(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        lifecycle_plan(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"rounds_per_batch": 21},
        {"batches": 6},
        {"warmup_rounds": 3},
        {"case_timeout_s": 241},
        {"settle_timeout_s": 6},
        {"sample_interval_s": 0},
        {"rss_ceiling_bytes": 2**32},
        {"max_samples": 12001},
        {"server_write_bytes": 2**20},
    ],
)
def test_lifecycle_config_enforces_hard_caps(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_lifecycle_config(replace(LifecycleConfig(), **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"concurrency": 1000},
        {"concurrency": True},
        {"repeat": 4},
        {"sequence": 0},
        {"mode": "sync-ish"},
        {"client": "aiohttp"},
        {"case": "lines-10k"},
    ],
)
def test_individual_worker_case_cannot_bypass_profile_caps(overrides: dict[str, object]) -> None:
    case = LifecycleCase(1, "foghttp", "async", "stream-1m", 1, 1)

    with pytest.raises(ValueError):
        validate_lifecycle_case(replace(case, **overrides))


def test_cli_lifecycle_uses_profile_defaults_and_preserves_explicit_lower_work(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(cli, "run_benchmark", run)

    result = CliRunner().invoke(
        cli.app,
        ["--suite", "response-streaming", "--streaming-profile", "lifecycle", "--requests", "1", "--no-progress"],
    )

    assert result.exit_code == 0, result.output
    args = run.await_args.args[0]
    assert args.clients == "foghttp,httpx"
    assert args.modes == "async,sync"
    assert args.concurrency == "1,10"
    assert args.requests == 1
    assert args.warmup == LifecycleConfig().warmup_rounds
    assert args.iterations == LifecycleConfig().batches
    assert args.scenarios == "first-chunk-close-1m,stream-1m"


def test_cli_lifecycle_rejects_other_suite_before_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(cli, "run_benchmark", run)

    result = CliRunner().invoke(cli.app, ["--streaming-profile", "lifecycle"])

    assert result.exit_code != 0
    run.assert_not_awaited()


def test_cli_default_does_not_expand_lifecycle_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(cli, "run_benchmark", run)

    result = CliRunner().invoke(cli.app, ["--suite", "response-streaming", "--no-progress"])

    assert result.exit_code == 0, result.output
    assert run.await_args.args[0].streaming_profile == "default"
    assert run.await_args.args[0].modes == "async"


def test_cancelled_launcher_preserves_partial_report_and_propagates_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_case = AsyncMock(side_effect=asyncio.CancelledError)
    write_report = Mock()
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", run_case)
    monkeypatch.setattr(lifecycle, "write_lifecycle_reports", write_report)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lifecycle.run_lifecycle_profile(lifecycle_args(tmp_path)))

    write_report.assert_called_once()
    results = write_report.call_args.args[0]
    assert results[0]["failure"]


def test_request_caps_fail_before_any_process_launch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_case = AsyncMock()
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", run_case)

    with pytest.raises(ValueError, match="request cap"):
        asyncio.run(lifecycle.run_lifecycle_profile(replace(lifecycle_args(tmp_path), requests=21)))

    run_case.assert_not_awaited()
