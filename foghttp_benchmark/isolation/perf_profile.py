__all__ = ("PerfProfileSession",)

from contextlib import ExitStack, suppress
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.perf_evidence import (
    DEFAULT_PERF_SAMPLE_FREQUENCY_HZ,
    PERF_SAMPLE_FREQUENCIES_HZ,
    inspect_perf_text,
)


ATTACH_DELAY_NS = 100_000_000
MAX_PROFILE_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
SAMPLE_DURATION_S = 0.5
EXTRACTION_TIMEOUT_S = 5


def _artifact(path: Path, *, limit: int = MAX_TEXT_BYTES) -> tuple[JsonObject, bytes]:
    size = path.stat().st_size
    if not 0 < size <= limit:
        msg = f"Perf artifact must be nonempty and no larger than {limit} bytes"
        raise ValueError(msg)
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) != size:
        msg = "Perf artifact changed during bounded capture"
        raise ValueError(msg)
    return {
        "path": str(path),
        "relative_path": f"profiles/{path.name}",
        "size_bytes": size,
        "sha256": hashlib.sha256(content).hexdigest(),
    }, content


def _read_recording(path: Path) -> JsonObject:
    artifact, content = _artifact(path, limit=MAX_PROFILE_BYTES)
    if not content.startswith(b"PERFILE2"):
        msg = "Raw perf artifact does not identify the supported perf.data file format"
        raise ValueError(msg)
    return artifact


def _extract_to_file(command: list[str], path: Path) -> None:
    with (
        path.open("x", encoding="utf-8") as stream,
        subprocess.Popen(  # noqa: S603 - resolved perf tool and owned input.
            command,
            stdout=stream,
            stderr=stream,
            text=True,
            start_new_session=True,
        ) as process,
    ):
        deadline = time.monotonic() + EXTRACTION_TIMEOUT_S
        try:
            while True:
                if path.stat().st_size > MAX_TEXT_BYTES:
                    msg = "Decoded perf artifact exceeds the bounded text output limit"
                    raise ValueError(msg)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, EXTRACTION_TIMEOUT_S)
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, command)
                return
        finally:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1)


class PerfProfileSession:
    def __init__(
        self,
        *,
        role: str,
        pid: int,
        output: Path,
        files: ExitStack,
        sample_frequency_hz: int = DEFAULT_PERF_SAMPLE_FREQUENCY_HZ,
    ) -> None:
        if str(sys.platform) != "linux" or role not in {"client", "server"} or type(pid) is not int or pid <= 0:
            msg = "Perf profiling requires Linux and an owned client/server PID"
            raise TypeError(msg)
        if type(sample_frequency_hz) is not int or sample_frequency_hz not in PERF_SAMPLE_FREQUENCIES_HZ:
            msg = "Perf sampling frequency must be 499 or 1999 Hz"
            raise ValueError(msg)
        self.sample_frequency_hz = sample_frequency_hz
        clock = time.get_clock_info("perf_counter")
        if clock.implementation != "clock_gettime(CLOCK_MONOTONIC)" or not clock.monotonic:
            msg = "Perf monotonic sample timestamps require Python CLOCK_MONOTONIC load boundaries"
            raise ValueError(msg)
        self.python_clock = {"implementation": clock.implementation, "resolution_s": clock.resolution}
        executable = shutil.which("perf")
        if executable is None:
            msg = "Linux perf executable is unavailable; profiling cannot fall back to unprofiled execution"
            raise FileNotFoundError(msg)
        self.tool = Path(executable).resolve(strict=True)
        version = subprocess.run(  # noqa: S603 - resolved tool, fixed version argument, no shell.
            [str(self.tool), "version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=EXTRACTION_TIMEOUT_S,
        )
        self.tool_version = version.stdout.strip()
        if not self.tool_version.startswith("perf version "):
            msg = "Resolved perf executable did not identify its version"
            raise ValueError(msg)
        with self.tool.open("rb") as stream:
            self.tool_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        self.role, self.target_pid, self.files = role, pid, files
        self.directory = output.resolve() / "profiles"
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / "perf.data"
        self.stdout = self.directory / "perf-record-stdout.txt"
        self.stderr = self.directory / "perf-record-stderr.txt"
        if any(self.directory.iterdir()):
            msg = "Perf profile directory already contains files"
            raise FileExistsError(msg)
        self.command = [
            str(self.tool),
            "record",
            "--clockid",
            "mono",
            "-F",
            str(sample_frequency_hz),
            *(["--strict-freq"] if sample_frequency_hz != DEFAULT_PERF_SAMPLE_FREQUENCY_HZ else []),
            "-e",
            "cpu-clock:u",
            "--call-graph",
            "dwarf,8192",
            "-p",
            str(pid),
            "-o",
            str(self.path),
            "--",
            "/usr/bin/sleep",
            str(SAMPLE_DURATION_S),
        ]
        self.process: subprocess.Popen[str] | None = None
        self.marker_seen_ns: int | None = None
        self.started_ns: int | None = None
        self.finished_ns: int | None = None
        self.cleanup_interrupted = False

    def tick(self, phase: str) -> None:
        now = time.perf_counter_ns()
        if phase == "batch_1_start" and self.marker_seen_ns is None:
            self.marker_seen_ns = now
        if self.process is None and self.marker_seen_ns is not None and now >= self.marker_seen_ns + ATTACH_DELAY_NS:
            if phase != "batch_1_start":
                msg = "Measured load ended before scheduled perf attach"
                raise RuntimeError(msg)
            self.started_ns = time.perf_counter_ns()
            self.process = subprocess.Popen(  # noqa: S603 - resolved perf executable, fixed event and owned PID.
                self.command,
                stdout=self.files.enter_context(self.stdout.open("x", encoding="utf-8")),
                stderr=self.files.enter_context(self.stderr.open("x", encoding="utf-8")),
                text=True,
                start_new_session=True,
            )
        self.poll()
        if self.process is not None and self.process.returncode not in {None, 0}:
            msg = f"Perf profiler exited with code {self.process.returncode}"
            raise RuntimeError(msg)

    def poll(self) -> None:
        if self.process is not None and self.process.poll() is not None and self.finished_ns is None:
            self.finished_ns = time.perf_counter_ns()

    def before_cleanup(self) -> None:
        self.poll()
        self.cleanup_interrupted = self.process is not None and self.process.returncode is None

    def finalize(self, client_report: JsonObject | None) -> tuple[JsonObject, list[str]]:
        self.poll()
        payload: JsonObject = {
            "profiler": "perf",
            "status": "failed",
            "target_role": self.role,
            "target_pid": self.target_pid,
            "profiler_pid": self.process.pid if self.process is not None else None,
            "returncode": self.process.returncode if self.process is not None else None,
            "cleanup_interrupted": self.cleanup_interrupted,
            "command": self.command,
            "tool_path": str(self.tool),
            "tool_version": self.tool_version,
            "tool_sha256": self.tool_sha256,
            "marker_seen_ns": self.marker_seen_ns,
            "attach_delay_ns": ATTACH_DELAY_NS,
            "tool_started_ns": self.started_ns,
            "tool_finished_ns": self.finished_ns,
            "sample_duration_s": SAMPLE_DURATION_S,
            "sample_frequency_hz": self.sample_frequency_hz,
            "qualification": "unqualified",
            "qualification_reason": "Perf capture did not complete with verified scope",
            "clock": "CLOCK_MONOTONIC (clockid 1); time.perf_counter_ns; nanoseconds",
            "python_clock": self.python_clock,
            "scope": "Owned target user-space on-CPU samples only; profiler excluded from client/server resource roles",
            "limitation": (
                "Software CPU-clock sampling excludes kernel CPU, blocked time and off-CPU latency; "
                "8192-byte DWARF stack snapshots, optimized frames, missing symbols and sampling perturbation "
                "limit attribution. Sample periods retain frequency weights, not exact user CPU duration. "
                "A qualified profile proves sample scope, not complete call chains or exact cost partition."
            ),
        }
        failures: list[str] = []
        if self.process is None or self.process.returncode != 0 or self.cleanup_interrupted:
            failures.append("Perf profiler did not finish successfully before owned cleanup")
        if not failures:
            try:
                payload.update(_read_recording(self.path))
                text = self._extract(payload)
                payload.update(
                    inspect_perf_text(pid=self.target_pid, sample_frequency_hz=self.sample_frequency_hz, **text),
                )
                self._qualify(payload, client_report)
            except (OSError, subprocess.SubprocessError, TypeError, ValueError) as error:
                failures.append(f"Invalid perf profile: {error}")
        payload.update(failures=failures, status="failed" if failures else "ok")
        return payload, failures

    def _extract(self, payload: JsonObject) -> dict[str, str]:
        commands = {
            "header": ["report", "--header-only", "--stdio"],
            "script": [
                "script",
                "--ns",
                "--header",
                "--show-lost-events",
                "-F",
                "comm,pid,tid,time,period,event,ip,sym,dso",
            ],
            "summary": ["report", "--stdio", "--no-children", "--percent-limit", "100"],
        }
        text: dict[str, str] = {}
        artifacts: JsonObject = {}
        for name, arguments in commands.items():
            path = self.directory / f"perf-{name}.txt"
            command = [str(self.tool), *arguments, "-i", str(self.path)]
            _extract_to_file(command, path)
            artifact, content = _artifact(path)
            artifacts[name] = {**artifact, "command": command}
            text[name] = content.decode("utf-8")
        artifact, content = _artifact(self.stderr)
        artifacts["record_stderr"] = artifact
        text["record_stderr"] = content.decode("utf-8")
        payload["text_artifacts"] = artifacts
        return text

    def _qualify(self, payload: JsonObject, client_report: JsonObject | None) -> None:
        batches = client_report.get("batches") if client_report is not None else None
        if not isinstance(batches, list) or len(batches) != 1 or not isinstance(batches[0], dict):
            msg = "Perf profile requires exactly one measured batch"
            raise ValueError(msg)
        timing = batches[0].get("timing")
        if not isinstance(timing, dict):
            msg = "Perf profile requires actual measured load timestamps"
            raise TypeError(msg)
        start, finish = timing.get("load_started_ns"), timing.get("load_finished_ns")
        if type(start) is not int or type(finish) is not int or not 0 < start < finish:
            msg = "Perf measured load timestamps must be positive and ordered"
            raise ValueError(msg)
        if self.started_ns is None or self.finished_ns is None or self.started_ns >= self.finished_ns:
            msg = "Perf invocation boundaries are missing or unordered"
            raise ValueError(msg)
        overlap = max(0, min(finish, self.finished_ns) - max(start, self.started_ns))
        samples_first, samples_last = payload.get("first_sample_ns"), payload.get("last_sample_ns")
        qualified = (
            start <= self.started_ns < self.finished_ns <= finish
            and type(samples_first) is int
            and type(samples_last) is int
            and start <= samples_first <= samples_last <= finish
        )
        payload.update(
            load_started_ns=start,
            load_finished_ns=finish,
            tool_load_overlap_ns=overlap,
            tool_outside_load_ns=self.finished_ns - self.started_ns - overlap,
            qualification="qualified" if qualified else "unqualified",
            qualification_reason=(
                "Full perf invocation and nonempty timestamped user CPU samples lie inside measured load"
                if qualified
                else "Empty or mixed/outside-load capture cannot establish measured-load-only on-CPU scope"
            ),
        )
