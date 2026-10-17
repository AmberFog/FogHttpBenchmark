__all__ = ("run_lifecycle_case",)

import asyncio
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import cast
from urllib.parse import urlsplit

from foghttp_benchmark.isolation.lifecycle_resources import LifecycleResourceSampler
from foghttp_benchmark.isolation.native_profile import NativeSampleSession
from foghttp_benchmark.isolation.perf_profile import PerfProfileSession
from foghttp_benchmark.isolation.process import tail_file_text
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.lifecycle_models import (
    LifecycleCase,
    LifecycleConfig,
    validate_lifecycle_case,
    validate_lifecycle_config,
)


POLL_S = 0.01
STARTUP_TIMEOUT_S = 5.0
MAX_CONTROL_BYTES = 65536
MAX_PHASES = 256
MAX_PHASE_NAME = 128
GROUP_QUIESCENCE_TIMEOUT_S = 0.05


@dataclass(slots=True)
class OwnedProcess:
    role: str
    process: subprocess.Popen[str]
    command: list[str]
    stdout: Path
    stderr: Path


def server_command(config: LifecycleConfig, ready_file: Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "foghttp_benchmark.streaming.lifecycle_server",
        "--ready-file",
        str(ready_file),
        "--body-bytes",
        str(config.body_bytes),
        "--write-bytes",
        str(config.server_write_bytes),
    ]
    if config.attribution is not None:
        command.extend(["--bytes-measurement", "--write-delay-s", str(config.attribution.server_delay_s)])
        if not config.attribution.server_observations:
            command.append("--no-body-observations")
    return command


def client_command(case_file: Path, server_url: str, control_dir: Path, output: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "foghttp_benchmark.streaming.lifecycle_worker",
        "--case-file",
        str(case_file),
        "--server-url",
        server_url,
        "--control-dir",
        str(control_dir),
        "--output",
        str(output),
    ]


def launch(command: list[str], role: str, output: Path, files: ExitStack) -> OwnedProcess:
    stdout = output / f"{role}-stdout.log"
    stderr = output / f"{role}-stderr.log"
    process = subprocess.Popen(  # noqa: S603 - owned Python modules and explicit arguments, without a shell.
        command,
        stdout=files.enter_context(stdout.open("w", encoding="utf-8")),
        stderr=files.enter_context(stderr.open("w", encoding="utf-8")),
        cwd=Path.cwd(),
        env=os.environ.copy(),
        text=True,
        start_new_session=True,
    )
    return OwnedProcess(role, process, command, stdout, stderr)


def read_object(path: Path, *, max_bytes: int = MAX_CONTROL_BYTES) -> JsonObject:
    if path.stat().st_size > max_bytes:
        msg = f"JSON exceeds {max_bytes} bytes: {path.name}"
        raise ValueError(msg)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = f"Expected a JSON object in {path.name}"
        raise TypeError(msg)
    return cast("JsonObject", value)


def write_object(path: Path, payload: JsonObject) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def group_has_live_members(group: int) -> bool:
    psutil = importlib.import_module("psutil")
    for pid in psutil.pids():
        try:
            if os.getpgid(pid) != group:
                continue
            if psutil.Process(pid).status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                return True
        except (ProcessLookupError, psutil.NoSuchProcess):
            continue
        except psutil.Error as error:
            msg = f"Cannot inspect possible owned process group {group}: {error}"
            raise RuntimeError(msg) from error
    return False


def group_quiescent_after_exit(owned: OwnedProcess) -> bool:
    try:
        owned.process.wait(timeout=GROUP_QUIESCENCE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False
    deadline = time.monotonic() + GROUP_QUIESCENCE_TIMEOUT_S
    while True:
        if not group_has_live_members(owned.process.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(POLL_S, remaining))


def signal_owned_group(owned: OwnedProcess, number: signal.Signals) -> str | None:
    # Poll first to reap a completed direct child before signalling its group.
    owned.process.poll()
    try:
        os.killpg(owned.process.pid, number)
    except ProcessLookupError:
        return None
    except PermissionError as error:
        try:
            if group_quiescent_after_exit(owned):
                return None
        except (OSError, RuntimeError) as verification_error:
            return f"Cannot verify owned group {owned.process.pid} after {error}: {verification_error}"
        return f"Cannot signal owned {owned.role} group {owned.process.pid}: {error}"
    except OSError as error:
        return f"Cannot signal owned {owned.role} group {owned.process.pid}: {error}"
    return None


def wait_owned_child(owned: OwnedProcess) -> str | None:
    try:
        owned.process.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        try:
            owned.process.kill()
            owned.process.wait(timeout=0.1)
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Cannot reap owned {owned.role} PID {owned.process.pid}: {error}"
    return None


async def reap_processes(processes: list[OwnedProcess], timeout_s: float) -> None:
    # Each child starts its own session. Signal the group even when its leader
    # has exited, so descendants cannot outlive timeout or partial startup.
    failures = [failure for owned in processes if (failure := signal_owned_group(owned, signal.SIGTERM))]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if all(owned.process.poll() is not None for owned in processes):
            break
        await asyncio.sleep(POLL_S)
    failures.extend(failure for owned in processes if (failure := signal_owned_group(owned, signal.SIGKILL)))
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if all(owned.process.poll() is not None for owned in processes):
            break
        await asyncio.sleep(POLL_S)
    failures.extend(failure for owned in processes if (failure := wait_owned_child(owned)))
    if failures:
        raise RuntimeError("; ".join(failures))


async def finish_cleanup(processes: list[OwnedProcess], timeout_s: float) -> None:
    cleanup = asyncio.create_task(reap_processes(processes, timeout_s))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


def check_marker(control: Path, sampler: LifecycleResourceSampler, sequence: int) -> tuple[int, list[str]]:
    path = control / "marker.json"
    try:
        marker = read_object(path)
    except FileNotFoundError:
        return sequence, []
    next_sequence = marker.get("sequence")
    if not isinstance(next_sequence, int) or isinstance(next_sequence, bool) or next_sequence < 1:
        msg = "Invalid phase marker sequence"
        raise ValueError(msg)
    if next_sequence == sequence:
        return sequence, []
    if next_sequence != sequence + 1 or next_sequence > MAX_PHASES:
        msg = "Out-of-order or excessive phase markers"
        raise ValueError(msg)
    phase = marker.get("phase")
    if not isinstance(phase, str) or not phase or len(phase) > MAX_PHASE_NAME:
        msg = "Invalid phase marker name"
        raise ValueError(msg)
    failures = sampler.mark(marker)
    write_object(control / "ack.json", {"sequence": next_sequence})
    return next_sequence, failures


async def await_server(
    server: OwnedProcess,
    ready_file: Path,
    sampler: LifecycleResourceSampler,
    deadline: float,
) -> str:
    startup_deadline = min(deadline, time.monotonic() + STARTUP_TIMEOUT_S)
    next_sample = 0.0
    while time.monotonic() < startup_deadline:
        if server.process.poll() is not None:
            msg = f"Server exited during startup with code {server.process.returncode}"
            raise RuntimeError(msg)
        if time.monotonic() >= next_sample:
            _, failures = sampler.sample("server-startup")
            if failures:
                raise RuntimeError(failures[0])
            next_sample = time.monotonic() + sampler.interval_s
        if file_exists(ready_file):
            ready = read_object(ready_file)
            url = ready.get("url")
            parsed = urlsplit(url) if isinstance(url, str) else None
            if ready.get("pid") != server.process.pid or parsed is None or parsed.hostname != "127.0.0.1":
                msg = "Server readiness identity or loopback URL mismatch"
                raise ValueError(msg)
            if parsed.scheme != "http" or parsed.port is None:
                msg = "Server readiness must describe a local HTTP endpoint"
                raise ValueError(msg)
            return cast("str", url)
        await asyncio.sleep(POLL_S)
    msg = "Server startup timeout or case deadline exceeded"
    raise TimeoutError(msg)


def tick_native_profile(
    profile: NativeSampleSession | PerfProfileSession | None,
    sampler: LifecycleResourceSampler,
) -> None:
    if profile is not None:
        phase = cast("str", sampler.phases[-1]["phase"]) if sampler.phases else "client-startup"
        profile.tick(phase)


async def monitor_client(
    client: OwnedProcess,
    server: OwnedProcess,
    control: Path,
    sampler: LifecycleResourceSampler,
    *,
    deadline: float,
    native_profile: NativeSampleSession | PerfProfileSession | None = None,
) -> list[str]:
    sequence = 0
    report_stamp = 0
    next_sample = 0.0
    while client.process.poll() is None:
        if time.monotonic() >= deadline:
            return ["Hard per-case deadline exceeded"]
        if server.process.poll() is not None:
            return [f"Server exited while client was active with code {server.process.returncode}"]
        sequence, failures = check_marker(control, sampler, sequence)
        if failures:
            return failures
        tick_native_profile(native_profile, sampler)
        if time.monotonic() >= next_sample:
            report_stamp, force_reap = worker_reap_request(control.parent / "client.json", report_stamp)
            if force_reap:
                return [force_reap]
            phase = cast("str", sampler.phases[-1]["phase"]) if sampler.phases else "client-startup"
            _, failures = sampler.sample(phase)
            if failures:
                return failures
            next_sample = time.monotonic() + sampler.interval_s
        await asyncio.sleep(POLL_S)
    _, failures = check_marker(control, sampler, sequence)
    if server.process.poll() is not None:
        failures.append(f"Server exited before owned shutdown with code {server.process.returncode}")
    if client.process.returncode:
        failures.append(f"Client exited with code {client.process.returncode}")
    return failures


def file_exists(path: Path) -> bool:
    return path.exists()


def worker_reap_request(path: Path, previous_stamp: int) -> tuple[int, str | None]:
    if not path.exists():
        return previous_stamp, None
    stamp = path.stat().st_mtime_ns
    if stamp == previous_stamp:
        return stamp, None
    report = read_object(path, max_bytes=16 * 1024 * 1024)
    reason = report.get("force_reap_reason")
    return stamp, f"Client requested forced process cleanup: {reason}" if reason else None


def prepare_output(output_dir: Path, case: LifecycleCase, config: LifecycleConfig) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    output_dir = output_dir.resolve()
    (output_dir / "control").mkdir()
    write_object(output_dir / "case.json", {"case": asdict(case), "config": asdict(config)})
    return output_dir


def initial_receipt(case: LifecycleCase, output_dir: Path) -> JsonObject:
    return {
        "case": asdict(case),
        "parent_pid": os.getpid(),
        "client_pid": None,
        "server_pid": None,
        "client_report": None,
        "report_path": None,
        "output_dir": str(output_dir),
    }


def finalize_receipt(
    receipt: JsonObject,
    processes: list[OwnedProcess],
    failures: list[str],
    sampler: LifecycleResourceSampler,
    output_dir: Path,
    *,
    native_profile: NativeSampleSession | PerfProfileSession | None = None,
) -> None:
    client = next((owned for owned in processes if owned.role == "client"), None)
    server = next((owned for owned in processes if owned.role == "server"), None)
    receipt["returncode"] = client.process.returncode if client is not None else -1
    receipt["server_returncode"] = server.process.returncode if server is not None else -1
    receipt["command"] = client.command if client is not None else []
    receipt["resources"] = sampler.payload()
    report = output_dir / "client.json"
    if report.exists():
        try:
            payload = read_object(report, max_bytes=16 * 1024 * 1024)
            receipt["client_report"] = payload
            receipt["report_path"] = str(report)
            if payload.get("status") != "ok" or payload.get("errors") != []:
                failures.append("Client lifecycle report contains failures")
        except (OSError, TypeError, ValueError) as error:
            failures.append(f"Invalid client lifecycle report: {error}")
    elif client is not None and not failures:
        failures.append("Client lifecycle report is missing")
    if native_profile is not None:
        profile, profile_failures = native_profile.finalize(cast("JsonObject | None", receipt["client_report"]))
        receipt["native_profile"] = profile
        failures.extend(profile_failures)
    receipt["failures"] = failures
    receipt["failure"] = failures[0] if failures else None
    receipt["status"] = "failed" if failures else "ok"
    for owned in processes:
        receipt[f"{owned.role}_stdout_tail"] = tail_file_text(owned.stdout)
        receipt[f"{owned.role}_stderr_tail"] = tail_file_text(owned.stderr)
    write_object(output_dir / "receipt.json", receipt)


async def run_lifecycle_case(case: LifecycleCase, config: LifecycleConfig, output_dir: Path) -> JsonObject:
    validate_lifecycle_case(case, config)
    validate_lifecycle_config(config)
    output_dir = prepare_output(output_dir, case, config)
    control = output_dir / "control"
    case_file = output_dir / "case.json"
    report = output_dir / "client.json"
    sampler = LifecycleResourceSampler(
        interval_s=config.sample_interval_s,
        max_samples=config.max_samples,
        rss_ceiling_bytes=config.rss_ceiling_bytes,
    )
    receipt = initial_receipt(case, output_dir)
    failures: list[str] = []
    processes: list[OwnedProcess] = []
    client: OwnedProcess | None = None
    server: OwnedProcess | None = None
    native_profile: NativeSampleSession | PerfProfileSession | None = None
    deadline = time.monotonic() + config.case_timeout_s
    try:
        with ExitStack() as files:
            try:
                server = launch(server_command(config, output_dir / "server-ready.json"), "server", output_dir, files)
                processes.append(server)
                receipt["server_pid"] = server.process.pid
                sampler.attach(
                    "server",
                    server.process.pid,
                    completion=server.process.poll,
                    wait_for_exit=server.process.wait,
                )
                url = await await_server(server, output_dir / "server-ready.json", sampler, deadline)
                client = launch(client_command(case_file, url, control, report), "client", output_dir, files)
                processes.append(client)
                receipt["client_pid"] = client.process.pid
                sampler.attach(
                    "client",
                    client.process.pid,
                    completion=client.process.poll,
                    wait_for_exit=client.process.wait,
                )
                if config.attribution is not None and config.attribution.profiler in {
                    "sample-client",
                    "sample-server",
                    "perf-client",
                    "perf-server",
                }:
                    target = client if config.attribution.profiler.endswith("-client") else server
                    if config.attribution.profiler.startswith("perf-"):
                        native_profile = PerfProfileSession(
                            role=target.role,
                            pid=target.process.pid,
                            output=output_dir,
                            files=files,
                            sample_frequency_hz=config.attribution.perf_sample_frequency_hz,
                        )
                    else:
                        native_profile = NativeSampleSession(
                            role=target.role,
                            pid=target.process.pid,
                            output=output_dir,
                            files=files,
                        )
                failures.extend(
                    await monitor_client(
                        client,
                        server,
                        control,
                        sampler,
                        deadline=deadline,
                        native_profile=native_profile,
                    ),
                )
            finally:
                if native_profile is not None:
                    native_profile.before_cleanup()
                    if native_profile.process is not None:
                        processes.append(
                            OwnedProcess(
                                "profiler",
                                native_profile.process,
                                native_profile.command,
                                native_profile.stdout,
                                native_profile.stderr,
                            ),
                        )
                await finish_cleanup(processes, config.settle_timeout_s)
    except asyncio.CancelledError:
        failures.append("Parent lifecycle operation cancelled")
        raise
    except Exception as error:  # noqa: BLE001 - preserve bounded output for startup/control/OS failures.
        failures.append(f"{type(error).__name__}: {error}")
    finally:
        finalize_receipt(receipt, processes, failures, sampler, output_dir, native_profile=native_profile)
    return receipt
