import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from foghttp_benchmark import cli
from foghttp_benchmark.isolation.lifecycle import run_lifecycle_case
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig, validate_lifecycle_config


@pytest.mark.parametrize("observations", [False, True])
def test_window_stream_limit_preserves_integrity_controls_and_compact_health(
    tmp_path: Path,
    *,
    observations: bool,
) -> None:
    config = LifecycleConfig(
        body_bytes=16_384,
        server_write_bytes=1024,
        warmup_rounds=1,
        batches=1,
        rounds_per_batch=1,
        case_timeout_s=10,
        attribution=AttributionConfig(minimum_duration_s=1, max_window_streams=20, server_observations=observations),
    )
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 10, 1)

    receipt = asyncio.run(asyncio.wait_for(run_lifecycle_case(case, config, tmp_path / "case"), 15))

    assert receipt["status"] == "ok", receipt
    report = receipt["client_report"]
    assert report["scalar_sample_cap"] == config.attribution.max_window_streams
    batch = report["batches"][0]
    assert batch["requests"] == config.attribution.max_window_streams
    assert batch["window"]["target_reached"] is False
    assert batch["window"]["stop_reason"] == "stream-limit"
    assert batch["verified_success_bytes"] == config.body_bytes * batch["requests"]
    assert all(sample["eof"] and sample["sha256"] for sample in batch["samples"])
    assert batch["server_health"]["status"] == "ok"
    assert "streams" not in batch["server_health"]["after"]
    assert batch["server_health"]["after"]["body_observations"]["enabled"] is observations
    if observations:
        assert batch["server_delivery"]["deltas"]["streams"] == batch["requests"]
        assert (
            batch["server_delivery"]["deltas"]["write_calls"]
            == batch["requests"] * config.body_bytes // config.server_write_bytes
        )
    assert batch["overhead"]["replay_bytes"] == batch["total_observed_bytes"]
    assert report["warmup"]["requests"] == case.concurrency
    assert "window" not in report["warmup"]
    assert report["controls"]["recovery"]["status"] == "ok"
    assert report["controls"]["body_wait_cancel"]["status"] == "ok"
    assert report["controls"]["slow_consumer_cancel"]["status"] == "ok"


@pytest.mark.parametrize(
    "option,value",
    [
        ("--streaming-minimum-duration-s", "0.5"),
        ("--streaming-minimum-duration-s", "6"),
        ("--streaming-max-window-streams", "2049"),
    ],
)
def test_window_cli_rejects_invalid_limits_before_process_launch(
    option: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "research_provenance_from_env", lambda **_: {"verified": True})
    result = CliRunner().invoke(
        cli.app,
        [
            "--suite",
            "response-streaming",
            "--streaming-profile",
            "async-bytes",
            "--iterations",
            "1",
            option,
            value,
            "--no-progress",
        ],
    )

    assert result.exit_code != 0
    assert "Minimum load duration" in result.output or "hard limit" in result.output


def test_window_cannot_expand_legacy_rounds_or_batches() -> None:
    config = LifecycleConfig(attribution=AttributionConfig(minimum_duration_s=1), batches=1)
    for invalid in (replace(config, rounds_per_batch=21), replace(config, batches=2)):
        with pytest.raises(ValueError):
            validate_lifecycle_config(invalid)
