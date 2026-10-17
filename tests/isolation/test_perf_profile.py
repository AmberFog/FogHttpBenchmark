import asyncio
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from foghttp_benchmark.isolation import lifecycle, perf_profile
from foghttp_benchmark.isolation.perf_profile import PerfProfileSession
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase
from tests.isolation.lifecycle_process_support import configure_fixtures, process_alive
from tests.isolation.perf_profile_support import DENSE_FREQUENCY_HZ, fake_perf
from tests.isolation.test_native_profile import CLIENT_CODE, fixture_config


def configure_perf_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str = "ok") -> None:
    configure_fixtures(monkeypatch)
    fake_perf(tmp_path, monkeypatch, mode=mode)
    monkeypatch.setattr(
        lifecycle,
        "client_command",
        lambda _case, _url, control, output: [sys.executable, "-c", CLIENT_CODE, str(control), str(output)],
    )


@pytest.mark.parametrize("role", ["client", "server"])
@pytest.mark.parametrize("frequency", [499, 1999])
def test_perf_owned_capture_and_decoding_preserve_load_scope_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    frequency: int,
) -> None:
    configure_perf_fixture(tmp_path, monkeypatch)
    config = fixture_config(role)
    config = replace(
        config,
        attribution=replace(
            config.attribution,
            profiler=f"perf-{role}",
            minimum_duration_s=1,
            perf_sample_frequency_hz=frequency,
        ),
    )
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(case, config, tmp_path / "case"))

    assert receipt["status"] == "ok", receipt["failures"]
    metadata = receipt["native_profile"]
    assert metadata["qualification"] == "qualified"
    assert metadata["sample_frequency_hz"] == frequency
    assert metadata["command"][metadata["command"].index("-F") + 1] == str(frequency)
    assert ("--strict-freq" in metadata["command"]) is (frequency == DENSE_FREQUENCY_HZ)
    assert metadata["sample_pids"] == [receipt[f"{role}_pid"]]
    expected_samples = 2
    assert metadata["sample_count"] == expected_samples
    assert set(metadata["text_artifacts"]) == {"header", "script", "summary", "record_stderr"}
    assert not process_alive(metadata["profiler_pid"])
    assert {item["role"] for item in receipt["resources"]["samples"]} == {"client", "server"}


@pytest.mark.parametrize("mode", ["foreign", "exit"])
def test_perf_attach_failure_or_foreign_samples_fail_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    configure_perf_fixture(tmp_path, monkeypatch, mode=mode)
    config = fixture_config()
    config = replace(config, attribution=replace(config.attribution, profiler="perf-client", minimum_duration_s=1))

    receipt = asyncio.run(
        lifecycle.run_lifecycle_case(LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1), config, tmp_path / "case"),
    )

    assert receipt["status"] == "failed"
    assert receipt["native_profile"]["status"] == "failed"
    assert not process_alive(receipt["native_profile"]["profiler_pid"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_cancelled_perf_fixture_reaps_profiler_client_and_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_perf_fixture(tmp_path, monkeypatch, mode="hang")
    config = fixture_config()
    config = replace(config, attribution=replace(config.attribution, profiler="perf-client", minimum_duration_s=1))
    output = tmp_path / "case"

    async def cancel() -> None:
        task = asyncio.create_task(
            lifecycle.run_lifecycle_case(LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1), config, output),
        )
        async with asyncio.timeout(3):
            while True:
                if (output / "profiles" / "profiler-pid").exists():
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(cancel())
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["native_profile"]["cleanup_interrupted"]
    assert not process_alive(receipt["native_profile"]["profiler_pid"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_missing_perf_never_silently_disables_requested_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_perf(tmp_path, monkeypatch)
    monkeypatch.setattr(perf_profile.shutil, "which", lambda _name: None)
    with ExitStack() as files, pytest.raises(FileNotFoundError, match="cannot fall back"):
        PerfProfileSession(role="client", pid=123, output=tmp_path, files=files)
