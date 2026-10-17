from contextlib import ExitStack
import importlib
import os
import signal
import sys
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

from foghttp_benchmark.isolation import lifecycle
from foghttp_benchmark.isolation.lifecycle_resources import LifecycleResourceSampler, ResourceSample


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


SERVER_CODE = """
import json, os, pathlib, sys, time
ready = pathlib.Path(sys.argv[1])
temporary = ready.with_suffix('.tmp')
temporary.write_text(json.dumps({'pid': os.getpid(), 'url': 'http://127.0.0.1:1'}))
temporary.replace(ready)
print('fixture server ready', flush=True)
time.sleep(100)
"""
SUCCESS_CODE = """
import json, os, pathlib, sys, time
control = pathlib.Path(sys.argv[1])
temporary = control / 'marker.tmp'
temporary.write_text(json.dumps({'sequence': 1, 'phase': 'before-load'}))
temporary.replace(control / 'marker.json')
while not (control / 'ack.json').exists():
    time.sleep(0.01)
output = pathlib.Path(sys.argv[2])
temporary = output.with_suffix('.tmp')
temporary.write_text(json.dumps({'status': 'ok', 'errors': [], 'pid': os.getpid()}))
temporary.replace(output)
print('fixture client done', flush=True)
"""
HANG_CODE = """
import os, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
print('fixture client waits', flush=True)
time.sleep(100)
"""
DESCENDANT_CODE = """
import pathlib, subprocess, sys, time
child = 'import os,pathlib,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
child += 'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(100)'
subprocess.Popen([sys.executable, '-c', child, sys.argv[1]])
while not pathlib.Path(sys.argv[1]).exists():
    time.sleep(0.01)
print('fixture descendant ready', flush=True)
time.sleep(100)
"""
FORCE_REAP_CODE = """
import json, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
output = pathlib.Path(sys.argv[1])
temporary = output.with_suffix('.tmp')
temporary.write_text(json.dumps({'status': 'failed', 'errors': ['unsettled'],
    'force_reap_reason': 'owned worker refused cancellation'}))
temporary.replace(output)
print('fixture requests forced cleanup', flush=True)
time.sleep(100)
"""


def configure_fixtures(monkeypatch: "pytest.MonkeyPatch", client_code: str = SUCCESS_CODE) -> None:
    monkeypatch.setattr(
        lifecycle,
        "server_command",
        lambda _config, ready: [sys.executable, "-c", SERVER_CODE, str(ready)],
    )

    def command(_case_file: "Path", _url: str, control: "Path", output: "Path") -> list[str]:
        arguments = [str(control), str(output)] if client_code == SUCCESS_CODE else [str(output.parent / "client-pid")]
        if client_code == FORCE_REAP_CODE:
            arguments = [str(output)]
        return [sys.executable, "-c", client_code, *arguments]

    monkeypatch.setattr(lifecycle, "client_command", command)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def process_executing(pid: int) -> bool:
    psutil = importlib.import_module("psutil")
    try:
        process = psutil.Process(pid)
        return bool(process.is_running() and process.status() != psutil.STATUS_ZOMBIE)
    except psutil.NoSuchProcess:
        return False


def configure_exit_race(
    monkeypatch: "pytest.MonkeyPatch",
    *,
    deny_rss: bool = False,
    completion_lag: bool = False,
) -> None:
    original = LifecycleResourceSampler.sample
    forced = False

    def sample(sampler: LifecycleResourceSampler, phase: str) -> tuple[dict[str, ResourceSample], list[str]]:
        nonlocal forced
        if not forced and sampler.phases and phase == "before-load":
            forced = True
            probe = sampler.probes["client"]
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if probe.completion is not None and probe.completion() is not None:
                    break
                time.sleep(0.005)
            else:
                msg = "Fixture client did not exit after phase acknowledgement"
                raise RuntimeError(msg)
            if completion_lag:
                probe.completion = lambda: None
            if deny_rss:
                psutil = importlib.import_module("psutil")

                def denied() -> None:
                    raise psutil.AccessDenied(probe.pid)

                probe.process = SimpleNamespace(memory_info=denied)
        return original(sampler, phase)

    monkeypatch.setattr(LifecycleResourceSampler, "sample", sample)


def completed_process_pair(output: "Path", server_code: int) -> tuple[lifecycle.OwnedProcess, lifecycle.OwnedProcess]:
    with ExitStack() as files:
        server = lifecycle.launch([sys.executable, "-c", f"raise SystemExit({server_code})"], "server", output, files)
        client = lifecycle.launch([sys.executable, "-c", "raise SystemExit(0)"], "client", output, files)
        server.process.wait(timeout=2)
        client.process.wait(timeout=2)
    return client, server


def configure_dead_group_permission_error(monkeypatch: "pytest.MonkeyPatch", report: "Path") -> list[int]:
    original = lifecycle.os.killpg
    verified: list[int] = []
    group_check = lifecycle.group_has_live_members

    def signal_group(group: int, number: signal.Signals) -> None:
        if report.exists() and lifecycle.read_object(report)["pid"] == group:
            msg = "Fixture EPERM for the already completed child group"
            raise PermissionError(msg)
        original(group, number)

    def verify_group(group: int) -> bool:
        verified.append(group)
        return group_check(group)

    monkeypatch.setattr(lifecycle.os, "killpg", signal_group)
    monkeypatch.setattr(lifecycle, "group_has_live_members", verify_group)
    return verified


def configure_live_group_permission_error(monkeypatch: "pytest.MonkeyPatch", pid_file: "Path") -> None:
    original = lifecycle.os.killpg

    def signal_group(group: int, number: signal.Signals) -> None:
        if pid_file.exists() and int(pid_file.read_text()) == group:
            msg = "Fixture EPERM for an owned live child group"
            raise PermissionError(msg)
        original(group, number)

    monkeypatch.setattr(lifecycle.os, "killpg", signal_group)
