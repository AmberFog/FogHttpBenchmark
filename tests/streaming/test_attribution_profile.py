import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import cli
from foghttp_benchmark.application import execution
from foghttp_benchmark.streaming import lifecycle
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.lifecycle_models import (
    LifecycleCase,
    LifecycleConfig,
    lifecycle_config_from_payload,
    validate_lifecycle_case,
    validate_lifecycle_config,
)
from tests.streaming.lifecycle_profile_factory import lifecycle_args


READ_BYTES = 512
PAYLOAD_BYTES = 16_384
SERVER_WRITE_BYTES = 1024
SERVER_DELAY_S = 0.001
CONSUMER_DELAY_S = 0.002
CHUNK_CAP = 8


def test_async_bytes_cli_preserves_explicit_measurement_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)
    result = CliRunner().invoke(
        cli.app,
        [
            "--suite",
            "response-streaming",
            "--streaming-profile",
            "async-bytes",
            "--clients",
            "httpx",
            "--requests",
            "1",
            "--streaming-payload-bytes",
            "16384",
            "--streaming-server-write-bytes",
            "1024",
            "--streaming-read-bytes",
            "512",
            "--streaming-server-delay-s",
            "0.001",
            "--streaming-consumer-delay-s",
            "0.002",
            "--streaming-instrumentation",
            "diagnostic",
            "--streaming-profiler-label",
            "external-test",
            "--streaming-chunk-sample-cap",
            "8",
            "--no-progress",
        ],
    )

    assert result.exit_code == 0, result.output
    args = run.await_args.args[0]
    assert (args.modes, args.scenarios, args.concurrency) == ("async", "stream-1m", "1,10")
    assert (args.clients, args.requests, args.repeats) == ("httpx", 1, 3)
    assert args.streaming_read_bytes == READ_BYTES
    assert args.streaming_payload_bytes == PAYLOAD_BYTES
    assert args.streaming_server_write_bytes == SERVER_WRITE_BYTES
    assert args.streaming_server_delay_s == SERVER_DELAY_S
    assert args.streaming_consumer_delay_s == CONSUMER_DELAY_S
    assert args.streaming_instrumentation == "diagnostic"
    assert args.streaming_profiler_label == "external-test"
    assert args.streaming_chunk_sample_cap == CHUNK_CAP


@pytest.mark.parametrize("profile", ["default", "lifecycle"])
def test_bytes_options_cannot_be_silently_ignored(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "run_benchmark", run)

    result = CliRunner().invoke(
        cli.app,
        [
            "--suite",
            "response-streaming",
            "--streaming-profile",
            profile,
            "--streaming-consumer-delay-s",
            "0.001",
        ],
    )

    assert result.exit_code != 0
    run.assert_not_awaited()


def test_async_bytes_cannot_launch_without_verified_installation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = AsyncMock()
    monkeypatch.setattr(execution, "research_provenance_from_env", lambda **_: None)
    monkeypatch.setattr(execution, "run_lifecycle_profile", run)

    with pytest.raises(ValueError, match="RESEARCH_MANIFEST"):
        asyncio.run(
            execution.run_benchmark(
                replace(lifecycle_args(tmp_path), streaming_profile="async-bytes"),
                show_progress=False,
            ),
        )

    run.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [{"modes": "sync"}, {"scenarios": "first-chunk-close-1m"}, {"streaming_read_bytes": 512}],
)
def test_async_bytes_rejects_unsupported_contract_before_launch(
    overrides: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = AsyncMock()
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", run)
    args = replace(lifecycle_args(tmp_path), streaming_profile="async-bytes", **overrides)

    with pytest.raises(ValueError):
        asyncio.run(lifecycle.run_lifecycle_profile(args))

    run.assert_not_awaited()


def test_nested_condition_config_survives_process_json_boundary() -> None:
    config = LifecycleConfig(attribution=AttributionConfig(consumer_delay_s=0.001, chunk_sample_cap=8))

    restored = lifecycle_config_from_payload(asdict(config))

    assert restored == config
    validate_lifecycle_config(restored)
    validate_lifecycle_case(LifecycleCase(1, "foghttp", "async", "stream-1m", 1, 1), restored)


def test_server_delays_cannot_predeclare_work_beyond_deadline() -> None:
    config = LifecycleConfig(server_write_bytes=1, attribution=AttributionConfig(server_delay_s=0.001))

    with pytest.raises(ValueError, match="deadline"):
        validate_lifecycle_config(config)


def test_cancelled_async_bytes_launch_preserves_invalid_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", run)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lifecycle.run_lifecycle_profile(replace(lifecycle_args(tmp_path), streaming_profile="async-bytes")))

    report = json.loads((tmp_path / "latest.json").read_text())
    assert report["metadata"]["validity"]["status"] == "invalid"
    assert report["runs"][0]["failure"]
    assert report["metadata"]["raw_evidence_validation"]["status"] == "ok"
