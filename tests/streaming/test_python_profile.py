import asyncio
import hashlib
import os
from pathlib import Path
import pstats
import sys
import threading
import time
from typing import Any

import pytest

from foghttp_benchmark.streaming import attribution_measure, python_profile
from foghttp_benchmark.streaming.attribution_consume import PendingStream
from foghttp_benchmark.streaming.attribution_measure import measure_async_batch
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from tests.streaming.attribution_support import BODY, AttributionClient, AttributionResponse


PROFILE_CONFIG = AttributionConfig(
    instrumentation="diagnostic",
    profiler_label="stdlib-cprofile-test",
    profiler="cprofile",
)


def profile_batch(
    path: Path | None,
    *,
    config: AttributionConfig = PROFILE_CONFIG,
    batch: int = 1,
) -> dict[str, Any]:
    return asyncio.run(
        measure_async_batch(
            AttributionClient(AttributionResponse([BODY])),
            "http://127.0.0.1/stream",
            body_bytes=len(BODY),
            concurrency=1,
            rounds=1,
            config=config,
            server_pid=999_999_999,
            batch=batch,
            python_profile_path=path,
        ),
    )


def test_real_cprofile_is_nonempty_bound_to_worker_and_stops_before_reporting(tmp_path: Path) -> None:
    path = tmp_path / "profiles" / "python-batch-001.pstats"

    batch = profile_batch(path)

    evidence = batch["python_profile"]
    assert batch["verified_success_bytes"] == len(BODY)
    assert evidence["status"] == "ok"
    assert evidence["pid"] == os.getpid()
    assert evidence["thread_id"] == threading.get_ident()
    assert evidence["enabling_thread_id"] == threading.get_ident()
    assert evidence["thread_scope"] == ("interpreter-monitoring" if hasattr(sys, "monitoring") else "enabling-thread")
    assert evidence["attribution_qualification"] == (
        "unqualified-cross-thread-context" if hasattr(sys, "monitoring") else "qualified-thread-scope"
    )
    assert evidence["path"] == str(path)
    assert evidence["relative_path"] == "profiles/python-batch-001.pstats"
    assert evidence["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert evidence["size_bytes"] == path.stat().st_size
    assert evidence["enabled_before_ns"] <= batch["timing"]["load_started_ns"]
    assert evidence["disabled_after_ns"] >= batch["timing"]["load_finished_ns"]
    assert evidence["load_started_ns"] == batch["timing"]["load_started_ns"]
    assert evidence["load_finished_ns"] == batch["timing"]["load_finished_ns"]
    assert "not process CPU" in evidence["timer"]
    assert not python_profile.active_python_instrumentation()
    assert pstats.Stats(str(path)).stats


@pytest.mark.parametrize("batch", [0, 1])
def test_default_and_warmup_do_not_create_or_enable_a_profile(
    batch: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_profile() -> None:
        msg = "Default and warmup must never instantiate a profiler"
        raise AssertionError(msg)

    monkeypatch.setattr(python_profile.cProfile, "Profile", forbidden_profile)
    path = tmp_path / "profiles" / "python-batch-001.pstats"
    config = AttributionConfig() if batch else PROFILE_CONFIG

    result = profile_batch(path, config=config, batch=batch)

    assert "python_profile" not in result
    assert not path.exists()


def test_requested_cprofile_without_owned_output_fails_before_load() -> None:
    with pytest.raises(ValueError, match="worker-owned profile path"):
        profile_batch(None)


@pytest.mark.parametrize("hook", ["getprofile", "gettrace"])
def test_existing_profile_or_trace_hook_is_never_replaced(
    hook: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_hook = object()
    monkeypatch.setattr(python_profile.sys, hook, lambda: active_hook)

    with pytest.raises(ValueError, match="existing Python profiler or trace hook"):
        profile_batch(tmp_path / "profile.pstats")

    assert getattr(sys, hook)() is active_hook


def test_existing_real_cprofile_is_detected_across_python_monitoring_backends(tmp_path: Path) -> None:
    profiler = python_profile.cProfile.Profile()
    try:
        profiler.enable()
        assert python_profile.active_python_instrumentation()
        with pytest.raises(ValueError, match="existing Python profiler or trace hook"):
            profile_batch(tmp_path / "profile.pstats")
    finally:
        profiler.disable()

    assert not python_profile.active_python_instrumentation()


def test_existing_profile_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "profile.pstats"
    path.write_bytes(b"existing evidence")

    with pytest.raises(FileExistsError, match="already exists"):
        profile_batch(path)

    assert path.read_bytes() == b"existing evidence"


def test_profile_covers_load_and_excludes_cpu_end_digest_replay_and_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    active = [False]
    counter = [0]
    finalize = PendingStream.finalize
    consume = attribution_measure.consume_attribution_stream

    class Profile:
        def enable(self) -> None:
            active[0] = True
            events.append("enable")

        def disable(self) -> None:
            active[0] = False
            events.append("disable")

        def dump_stats(self, path: str) -> None:
            assert not active[0]
            events.append("dump")
            Path(path).write_bytes(b"profile")

    def clock() -> int:
        counter[0] += 1
        return counter[0]

    def cpu(pid: int) -> dict[str, Any]:
        assert not active[0]
        events.append("cpu")
        return {
            "pid": pid,
            "user_s": 0.0,
            "system_s": 0.0,
            "reason": None,
            "probe_started_ns": clock(),
            "probe_finished_ns": clock(),
        }

    async def loaded(*args: object, **kwargs: Any) -> PendingStream:
        assert active[0]
        events.append("load")
        return await consume(*args, **kwargs)

    def finalized(self: PendingStream, **kwargs: Any) -> dict[str, Any]:
        assert not active[0]
        events.append("digest")
        return finalize(self, **kwargs)

    def replay(*_args: object, **_kwargs: object) -> dict[str, Any]:
        assert not active[0]
        events.append("replay")
        return {"status": "ok"}

    monkeypatch.setattr(python_profile.cProfile, "Profile", Profile)
    monkeypatch.setattr(attribution_measure.time, "perf_counter_ns", clock)
    monkeypatch.setattr(attribution_measure, "_cpu_snapshot", cpu)
    monkeypatch.setattr(attribution_measure, "consume_attribution_stream", loaded)
    monkeypatch.setattr(PendingStream, "finalize", finalized)
    monkeypatch.setattr(attribution_measure, "replay_harness_overhead", replay)

    batch = profile_batch(tmp_path / "profiles" / "batch.pstats")

    assert events == ["cpu", "cpu", "enable", "load", "disable", "cpu", "cpu", "digest", "replay", "dump"]
    evidence = batch["python_profile"]
    assert evidence["enabled_before_ns"] < evidence["load_started_ns"]
    assert evidence["load_finished_ns"] < evidence["disabled_after_ns"]


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_error_and_cancellation_disable_profiler_without_success_artifact(
    error_type: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "profiles" / "batch.pstats"

    async def failed(*_args: object, **_kwargs: object) -> PendingStream:
        assert python_profile.active_python_instrumentation()
        message = "load interrupted"
        raise error_type(message)

    monkeypatch.setattr(attribution_measure, "consume_attribution_stream", failed)

    with pytest.raises(error_type, match="load interrupted"):
        profile_batch(path)

    assert not python_profile.active_python_instrumentation()
    assert not path.exists()


def test_profile_disk_failure_is_not_reported_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_dump(self: python_profile.PythonLoadProfile, **_kwargs: object) -> dict[str, Any]:
        assert not python_profile.active_python_instrumentation()
        msg = "profile disk unavailable"
        raise OSError(msg)

    monkeypatch.setattr(python_profile.PythonLoadProfile, "write", failed_dump)

    with pytest.raises(OSError, match="profile disk unavailable"):
        profile_batch(tmp_path / "batch.pstats")


def test_actual_cprofile_thread_coverage_matches_recorded_backend_scope(tmp_path: Path) -> None:
    release = threading.Event()
    completed = threading.Event()

    def worker_marker() -> None:
        completed.set()

    def run_worker() -> None:
        if release.wait(timeout=2):
            worker_marker()

    thread = threading.Thread(target=run_worker)
    thread.start()
    profile = python_profile.PythonLoadProfile(tmp_path / "profiles" / "thread-scope.pstats")
    try:
        profile.start()
        started = time.perf_counter_ns()
        release.set()
        assert completed.wait(timeout=2)
        thread.join(timeout=2)
        assert not thread.is_alive()
        finished = time.perf_counter_ns()
    finally:
        profile.stop()
        release.set()
        thread.join(timeout=2)
    evidence = profile.write(load_started_ns=started, load_finished_ns=finished)
    captured = any(entry.code is worker_marker.__code__ for entry in profile.profiler.getstats())

    assert not thread.is_alive()
    assert captured is hasattr(sys, "monitoring")
    assert evidence["thread_scope"] == ("interpreter-monitoring" if captured else "enabling-thread")
    assert evidence["attribution_qualification"] == (
        "unqualified-cross-thread-context" if captured else "qualified-thread-scope"
    )
    assert not python_profile.active_python_instrumentation()
