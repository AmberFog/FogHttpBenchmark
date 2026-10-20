import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import cli
from foghttp_benchmark.application import execution
from foghttp_benchmark.streaming import lifecycle
from foghttp_benchmark.streaming.attribution_models import AttributionConfig, validate_attribution_config
from foghttp_benchmark.streaming.lifecycle_models import LifecycleConfig, validate_lifecycle_config
from tests.isolation.perf_profile_support import DENSE_FREQUENCY_HZ
from tests.streaming.lifecycle_profile_factory import lifecycle_args


@pytest.mark.parametrize(
    "profiler",
    ["unknown", "cprofile", "sample-client", "sample-server", "perf-client", "perf-server"],
)
def test_profiler_requires_known_backend_and_explicit_diagnostic_label(profiler: str) -> None:
    with pytest.raises(ValueError, match=r"Profiler|profiler"):
        validate_attribution_config(AttributionConfig(profiler=profiler))


@pytest.mark.parametrize("batches,duration", [(2, 2), (1, 0), (1, 1)])
def test_native_profile_rejects_insufficient_load_before_launch(batches: int, duration: float) -> None:
    config = LifecycleConfig(
        batches=batches,
        attribution=AttributionConfig(
            profiler="sample-client",
            profiler_label="native",
            instrumentation="diagnostic",
            minimum_duration_s=duration,
        ),
    )
    with pytest.raises(ValueError, match="Native sampling"):
        validate_lifecycle_config(config)


@pytest.mark.parametrize("batches,duration", [(2, 1), (1, 0)])
def test_perf_rejects_missing_window_before_process_launch(batches: int, duration: float) -> None:
    config = LifecycleConfig(
        batches=batches,
        attribution=AttributionConfig(
            profiler="perf-client",
            profiler_label="cpu",
            instrumentation="diagnostic",
            minimum_duration_s=duration,
        ),
    )
    with pytest.raises(ValueError, match="Linux perf sampling"):
        validate_lifecycle_config(config)


@pytest.mark.parametrize("profile", ["default", "lifecycle"])
def test_profiler_option_cannot_be_ignored(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)
    result = CliRunner().invoke(cli.app, ["--streaming-profile", profile, "--streaming-profiler", "cprofile"])
    assert result.exit_code != 0
    run.assert_not_awaited()


@pytest.mark.parametrize("backend,frequency", [("cprofile", 499), ("perf-client", 1999)])
def test_profiler_cli_configuration_reaches_isolated_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backend: str,
    frequency: int,
) -> None:
    run = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", run)
    args = replace(
        lifecycle_args(tmp_path),
        streaming_profile="async-bytes",
        streaming_instrumentation="diagnostic",
        streaming_profiler=backend,
        streaming_profiler_label="python-load",
        streaming_perf_sample_frequency_hz=frequency,
        streaming_minimum_duration_s=1,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lifecycle.run_lifecycle_profile(args))
    assert run.await_args.args[1].attribution.profiler == backend
    assert run.await_args.args[1].attribution.perf_sample_frequency_hz == frequency


@pytest.mark.parametrize("frequency", [True, 499.0, "1999", 0, 500, 2000])
def test_perf_frequency_outside_integer_allowlist_is_rejected_before_launch(frequency: object) -> None:
    config = AttributionConfig(
        profiler="perf-client",
        profiler_label="frequency-test",
        instrumentation="diagnostic",
        perf_sample_frequency_hz=frequency,
    )
    with pytest.raises(ValueError, match="frequency"):
        validate_attribution_config(config)


@pytest.mark.parametrize("backend", ["none", "cprofile", "sample-client", "sample-server"])
def test_dense_frequency_requires_active_perf_backend(backend: str) -> None:
    config = AttributionConfig(
        profiler=backend,
        profiler_label="frequency-test",
        instrumentation="diagnostic",
        perf_sample_frequency_hz=1999,
    )
    with pytest.raises(ValueError, match="active perf"):
        validate_attribution_config(config)


@pytest.mark.parametrize("profile", ["default", "lifecycle"])
def test_perf_frequency_option_cannot_be_ignored(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)
    result = CliRunner().invoke(
        cli.app,
        ["--streaming-profile", profile, "--streaming-perf-sample-frequency-hz", "1999"],
    )
    assert result.exit_code != 0
    run.assert_not_awaited()


def test_dense_perf_cli_option_reaches_benchmark_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)
    result = CliRunner().invoke(
        cli.app,
        [
            "--suite",
            "response-streaming",
            "--streaming-profile",
            "async-bytes",
            "--streaming-profiler",
            "perf-client",
            "--streaming-profiler-label",
            "dense-cpu",
            "--streaming-instrumentation",
            "diagnostic",
            "--streaming-perf-sample-frequency-hz",
            "1999",
        ],
    )
    assert result.exit_code == 0, result.output
    assert run.await_args.args[0].streaming_perf_sample_frequency_hz == DENSE_FREQUENCY_HZ
