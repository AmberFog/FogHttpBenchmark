__all__ = ("run_child_process",)

from dataclasses import replace
import importlib
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from foghttp_benchmark.isolation.models import (
    ChildProcessResult,
    ChildResourcePeaks,
    ClientIsolationPlanItem,
)


POLL_INTERVAL_S = 0.1
TAIL_LINES = 40
TAIL_CHARS = 4000
TAIL_READ_CHARS = TAIL_CHARS * 4
CHILD_OUTPUT_FILES = ("latest.json", "latest.md", "stdout.log", "stderr.log")


class ChildProcessSampler:
    def __init__(self, pid: int) -> None:
        self.peaks = ChildResourcePeaks(rss_mb=None, threads=None, fds=None)
        self._process: Any | None = None
        try:
            psutil = importlib.import_module("psutil")
        except ImportError:
            return
        try:
            self._process = psutil.Process(pid)
        except Exception:  # noqa: BLE001 - process may exit before psutil attaches.
            self._process = None

    def sample(self) -> None:
        if self._process is None:
            return
        try:
            rss_mb = self._process.memory_info().rss / 1024 / 1024
            threads = self._process.num_threads()
            fds_getter = getattr(self._process, "num_fds", None)
            fds = fds_getter() if fds_getter is not None else None
        except Exception:  # noqa: BLE001 - metrics are best-effort diagnostics.
            return

        self.peaks = replace(
            self.peaks,
            rss_mb=max(self.peaks.rss_mb or 0.0, rss_mb),
            threads=max(self.peaks.threads or 0, threads),
            fds=max(self.peaks.fds or 0, fds) if fds is not None else self.peaks.fds,
        )


def run_child_process(plan_item: ClientIsolationPlanItem, *, env: dict[str, str] | None = None) -> ChildProcessResult:
    started_at = time.monotonic()
    plan_item.output_dir.mkdir(parents=True, exist_ok=True)
    clear_stale_latest_files(plan_item.output_dir)
    stdout_path = plan_item.output_dir / "stdout.log"
    stderr_path = plan_item.output_dir / "stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(  # noqa: S603 - command is built from fixed CLI flags and selected client names.
            plan_item.command,
            cwd=str(Path.cwd()),
            env=os.environ.copy() if env is None else env,
            stderr=stderr_file,
            stdout=stdout_file,
            text=True,
        )
        sampler = ChildProcessSampler(process.pid)
        while process.poll() is None:
            sampler.sample()
            time.sleep(POLL_INTERVAL_S)
        returncode = process.wait()
    sampler.sample()
    duration_s = time.monotonic() - started_at
    report_path = plan_item.output_dir / "latest.json"

    return ChildProcessResult(
        sequence=plan_item.sequence,
        client=plan_item.client,
        scenario=plan_item.scenario,
        output_dir=str(plan_item.output_dir),
        report_path=str(report_path) if report_path.exists() else None,
        command=plan_item.command,
        returncode=returncode,
        duration_s=duration_s,
        peaks=sampler.peaks,
        stdout_tail=tail_file_text(stdout_path),
        stderr_tail=tail_file_text(stderr_path),
    )


def clear_stale_latest_files(output_dir: Path) -> None:
    for name in CHILD_OUTPUT_FILES:
        path = output_dir / name
        if path.exists():
            path.unlink()


def tail_file_text(path: Path) -> str:
    try:
        with path.open("rb") as file_handle:
            file_handle.seek(0, os.SEEK_END)
            file_size = file_handle.tell()
            file_handle.seek(max(file_size - TAIL_READ_CHARS, 0))
            value = file_handle.read().decode(errors="replace")
    except OSError:
        return ""
    return tail_text(value)


def tail_text(value: str) -> str:
    lines = value.splitlines()
    tail = "\n".join(lines[-TAIL_LINES:])
    if len(tail) <= TAIL_CHARS:
        return tail
    return tail[-TAIL_CHARS:]
