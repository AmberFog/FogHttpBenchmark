import asyncio
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from foghttp_benchmark.isolation import lifecycle, native_profile
from foghttp_benchmark.isolation.native_profile import NativeSampleSession
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from tests.isolation.lifecycle_process_support import configure_fixtures, process_alive


TARGET_PID = 12345
CLIENT_CODE = """
import json, os, pathlib, sys, time
control, output = map(pathlib.Path, sys.argv[1:])
temporary = control/'marker.tmp'
temporary.write_text(json.dumps({'sequence':1,'phase':'batch_1_start'}))
temporary.replace(control/'marker.json')
while not (control/'ack.json').exists(): time.sleep(.005)
started=time.perf_counter_ns()
time.sleep(.6)
finished=time.perf_counter_ns()
temporary = output.with_suffix('.tmp')
temporary.write_text(json.dumps({'status':'ok','errors':[],'pid':os.getpid(),
  'batches':[{'timing':{'load_started_ns':started,'load_finished_ns':finished}}]}))
temporary.replace(output)
"""
SAMPLE_CODE = """
import json, os, pathlib, signal, sys, time
target, output, mode = int(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
(output.parent/'profiler-pid').write_text(str(os.getpid()))
if mode=='hang':
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(100)
elif mode=='exit': raise SystemExit(23)
else:
    time.sleep(.02)
    if mode=='foreign': target+=1
    output.write_text('Analysis of sampling python (pid %d) every 1 millisecond\\n'
        'Process: python [%d]\\nCall graph:\\n    1 Thread_1\\n' % (target,target))
"""


def report(start: int = 1, finish: int = 1000) -> dict[str, object]:
    return {"batches": [{"timing": {"load_started_ns": start, "load_finished_ns": finish}}]}


def session(tmp_path: Path, files: ExitStack, monkeypatch: pytest.MonkeyPatch) -> NativeSampleSession:
    monkeypatch.setattr(native_profile, "sys", SimpleNamespace(platform="darwin"))
    return NativeSampleSession(role="client", pid=TARGET_PID, output=tmp_path, files=files)


def completed(profile: NativeSampleSession, *, pid: int = TARGET_PID, code: int = 0) -> None:
    profile.process = Mock(pid=999, returncode=code)
    profile.process.poll.return_value = code
    profile.started_ns, profile.finished_ns = 100, 900
    profile.path.write_text(
        f"Analysis of sampling python (pid {pid}) every 1 millisecond\n"
        f"Process: python [{pid}]\nCall graph:\n    1 Thread_1\n",
    )


def test_attach_is_delayed_and_poll_never_waits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Mock(return_value=1)
    monkeypatch.setattr(native_profile, "time", SimpleNamespace(perf_counter_ns=clock))
    child = Mock(pid=999, returncode=None)
    child.poll.return_value = None
    launch = Mock(return_value=child)
    monkeypatch.setattr(native_profile.subprocess, "Popen", launch)
    with ExitStack() as files:
        profile = session(tmp_path, files, monkeypatch)
        profile.tick("before-load")
        profile.tick("batch_1_start")
        clock.return_value = native_profile.ATTACH_DELAY_NS
        profile.tick("batch_1_start")
        launch.assert_not_called()
        clock.return_value += 1
        profile.tick("batch_1_start")
        profile.tick("batch_1_start")
        launch.assert_called_once()
        child.wait.assert_not_called()
        assert launch.call_args.args[0] == [
            "/usr/bin/sample",
            str(TARGET_PID),
            "1",
            "1",
            "-mayDie",
            "-file",
            str(profile.path),
        ]
        assert launch.call_args.kwargs["start_new_session"] is True


def test_profile_whole_invocation_inside_load_is_qualified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ExitStack() as files:
        profile = session(tmp_path, files, monkeypatch)
        completed(profile)
        metadata, failures = profile.finalize(report())
    assert failures == []
    assert metadata["status"] == "ok"
    assert metadata["qualification"] == "qualified"
    assert metadata["tool_outside_load_ns"] == 0
    assert metadata["pid_from_report"] == TARGET_PID
    assert metadata["sha256"]


@pytest.mark.parametrize(("start", "finish"), [(200, 1000), (1, 800), (1000, 2000)])
def test_mixed_or_absent_overlap_remains_explicitly_unqualified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start: int,
    finish: int,
) -> None:
    with ExitStack() as files:
        profile = session(tmp_path, files, monkeypatch)
        completed(profile)
        metadata, failures = profile.finalize(report(start, finish))
    assert failures == []
    assert metadata["status"] == "ok"
    assert metadata["qualification"] == "unqualified"
    assert metadata["tool_outside_load_ns"] > 0


@pytest.mark.parametrize("damage", ["foreign", "missing", "nonzero", "no-timing", "unstarted", "cleanup"])
def test_invalid_or_incomplete_profile_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    with ExitStack() as files:
        profile = session(tmp_path, files, monkeypatch)
        completed(profile, pid=TARGET_PID + 1 if damage == "foreign" else TARGET_PID)
        if damage == "missing":
            profile.path.unlink()
        elif damage == "nonzero":
            profile.process.returncode = 23
        elif damage == "unstarted":
            profile.process = None
        elif damage == "cleanup":
            profile.cleanup_interrupted = True
        metadata, failures = profile.finalize({} if damage == "no-timing" else report())
    assert failures
    assert metadata["status"] == "failed"


def test_existing_native_artifact_is_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ExitStack() as files:
        profile = session(tmp_path, files, monkeypatch)
        completed(profile)
        with pytest.raises(FileExistsError):
            session(tmp_path, files, monkeypatch)


def configure_native_fixture(monkeypatch: pytest.MonkeyPatch, *, mode: str = "ok") -> None:
    configure_fixtures(monkeypatch)
    monkeypatch.setattr(native_profile, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        lifecycle,
        "client_command",
        lambda _case, _url, control, output: [sys.executable, "-c", CLIENT_CODE, str(control), str(output)],
    )
    original = subprocess.Popen

    def launch(command: list[str], **kwargs: object) -> subprocess.Popen[str]:
        if command[0] == "/usr/bin/sample":
            command = [sys.executable, "-c", SAMPLE_CODE, command[1], command[-1], mode]
        return original(command, **kwargs)

    monkeypatch.setattr(native_profile.subprocess, "Popen", launch)


def fixture_config(role: str = "client") -> LifecycleConfig:
    return LifecycleConfig(
        batches=1,
        sample_interval_s=0.01,
        case_timeout_s=5,
        settle_timeout_s=0.1,
        attribution=AttributionConfig(
            instrumentation="diagnostic",
            profiler_label="test",
            profiler=f"sample-{role}",
            minimum_duration_s=3,
        ),
    )


@pytest.mark.parametrize("role", ["client", "server"])
def test_owned_native_profiler_is_proven_reaped_and_excluded_from_resource_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    configure_native_fixture(monkeypatch)
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
    receipt = asyncio.run(lifecycle.run_lifecycle_case(case, fixture_config(role), tmp_path / "case"))
    assert receipt["status"] == "ok", receipt["failures"]
    metadata = receipt["native_profile"]
    assert metadata["qualification"] == "qualified"
    assert metadata["target_pid"] == receipt[f"{role}_pid"]
    assert not process_alive(metadata["profiler_pid"])
    assert {item["role"] for item in receipt["resources"]["samples"]} == {"client", "server"}


@pytest.mark.parametrize("mode", ["foreign", "exit"])
def test_native_attach_failure_or_foreign_profile_invalidates_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    configure_native_fixture(monkeypatch, mode=mode)
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
    receipt = asyncio.run(lifecycle.run_lifecycle_case(case, fixture_config(), tmp_path / "case"))
    assert receipt["status"] == "failed"
    assert receipt["native_profile"]["status"] == "failed"
    assert not process_alive(receipt["native_profile"]["profiler_pid"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_cancel_reaps_active_native_profiler_with_existing_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_native_fixture(monkeypatch, mode="hang")
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
    output = tmp_path / "case"

    async def cancel() -> None:
        task = asyncio.create_task(lifecycle.run_lifecycle_case(case, fixture_config(), output))
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
    assert receipt["status"] == "failed"
    assert receipt["native_profile"]["cleanup_interrupted"]
    assert not process_alive(receipt["native_profile"]["profiler_pid"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_deadline_reaps_active_native_profiler_and_retains_partial_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_native_fixture(monkeypatch, mode="hang")
    monkeypatch.setattr(
        lifecycle,
        "client_command",
        lambda _case, _url, control, output: [
            sys.executable,
            "-c",
            CLIENT_CODE.replace("time.sleep(.6)", "time.sleep(100)"),
            str(control),
            str(output),
        ],
    )
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
    config = replace(fixture_config(), case_timeout_s=2.3)
    config = replace(config, attribution=replace(config.attribution, minimum_duration_s=2))
    receipt = asyncio.run(lifecycle.run_lifecycle_case(case, config, tmp_path / "case"))
    assert receipt["status"] == "failed"
    assert "deadline" in receipt["failure"]
    assert receipt["native_profile"]["cleanup_interrupted"]
    assert not process_alive(receipt["native_profile"]["profiler_pid"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])
