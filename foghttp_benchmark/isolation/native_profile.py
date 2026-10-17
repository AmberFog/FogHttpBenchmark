__all__ = ("NativeSampleSession",)

from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time

from foghttp_benchmark.models import JsonObject


ATTACH_DELAY_NS = 200_000_000
MAX_PROFILE_BYTES = 16 * 1024 * 1024
SAMPLE_DURATION_S = 1
SAMPLE_INTERVAL_MS = 1


class NativeSampleSession:
    def __init__(self, *, role: str, pid: int, output: Path, files: ExitStack) -> None:
        if sys.platform != "darwin" or role not in {"client", "server"} or type(pid) is not int or pid <= 0:
            msg = "Native sample requires macOS and an owned client/server PID"
            raise ValueError(msg)
        self.role = role
        self.target_pid = pid
        self.files = files
        self.path = output.resolve() / "profiles" / "native-sample.txt"
        self.stdout = output / "profiler-stdout.log"
        self.stderr = output / "profiler-stderr.log"
        self.path.parent.mkdir(exist_ok=True)
        if any(path.exists() for path in (self.path, self.stdout, self.stderr)):
            msg = "Native profile output or logs already exist"
            raise FileExistsError(msg)
        self.command = [
            "/usr/bin/sample",
            str(pid),
            str(SAMPLE_DURATION_S),
            str(SAMPLE_INTERVAL_MS),
            "-mayDie",
            "-file",
            str(self.path),
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
                msg = "Measured load phase ended before the scheduled native attach"
                raise RuntimeError(msg)
            self.started_ns = time.perf_counter_ns()
            self.process = subprocess.Popen(  # noqa: S603 - fixed sample executable and owned PID, without a shell.
                self.command,
                stdout=self.files.enter_context(self.stdout.open("x", encoding="utf-8")),
                stderr=self.files.enter_context(self.stderr.open("x", encoding="utf-8")),
                text=True,
                start_new_session=True,
            )
        self.poll()
        if self.process is not None and self.process.returncode not in {None, 0}:
            msg = f"Native profiler exited with code {self.process.returncode}"
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
            "profiler": "sample",
            "status": "failed",
            "target_role": self.role,
            "target_pid": self.target_pid,
            "profiler_pid": self.process.pid if self.process is not None else None,
            "returncode": self.process.returncode if self.process is not None else None,
            "command": self.command,
            "path": str(self.path),
            "relative_path": "profiles/native-sample.txt",
            "sample_duration_s": SAMPLE_DURATION_S,
            "sample_interval_ms": SAMPLE_INTERVAL_MS,
            "marker_seen_ns": self.marker_seen_ns,
            "attach_delay_ns": ATTACH_DELAY_NS,
            "tool_started_ns": self.started_ns,
            "tool_finished_ns": self.finished_ns,
            "cleanup_interrupted": self.cleanup_interrupted,
            "qualification": "unqualified",
            "qualification_reason": "Native profile did not complete with verified load boundaries",
            "clock": "time.perf_counter_ns; monotonic; nanoseconds",
            "timing_scope": (
                "Conservative full tool invocation: before process launch through observed exit, "
                "including attach, collection, symbolication and file output; not exact sampled instruction times"
            ),
            "scope": "Owned target only; profiler process excluded from client/server CPU and RSS samples",
            "limitation": (
                "All-thread periodic stack weights are thread-wall observations, not CPU percentages; "
                "blocked threads, profiling perturbation, inlining and missing symbols prevent exact cost partition"
            ),
        }
        failures: list[str] = []
        if self.process is None or self.process.returncode != 0 or self.cleanup_interrupted:
            failures.append("Native profiler did not finish successfully before owned cleanup")
        try:
            self._read_artifact(payload)
            self._qualify(payload, client_report)
        except (OSError, TypeError, ValueError) as error:
            failures.append(f"Invalid native profile: {error}")
        payload["failures"] = failures
        payload["status"] = "failed" if failures else "ok"
        return payload, failures

    def _read_artifact(self, payload: JsonObject) -> None:
        size = self.path.stat().st_size
        if not 0 < size <= MAX_PROFILE_BYTES:
            msg = "Native profile must be nonempty and bounded by 16 MiB"
            raise ValueError(msg)
        content = self.path.read_bytes()
        payload.update({"size_bytes": size, "sha256": hashlib.sha256(content).hexdigest()})
        text = content.decode("utf-8")
        process = re.search(r"^Process:\s+.+\[(\d+)\]\s*$", text, flags=re.MULTILINE)
        analysis = re.search(
            r"^Analysis of sampling .+ \(pid (\d+)\) every 1 millisecond\s*$",
            text,
            flags=re.MULTILINE,
        )
        if process is None or analysis is None or "Call graph:" not in text:
            msg = "Native profile is missing process identity or sampled call graph"
            raise ValueError(msg)
        pids = [int(process.group(1)), int(analysis.group(1))]
        payload.update({"pid_from_report": pids[0], "pid_from_analysis_header": pids[1]})
        if pids != [self.target_pid, self.target_pid]:
            msg = "Native profile PID does not match the owned target"
            raise ValueError(msg)

    def _qualify(self, payload: JsonObject, client_report: JsonObject | None) -> None:
        batches = client_report.get("batches") if client_report is not None else None
        if not isinstance(batches, list) or len(batches) != 1 or not isinstance(batches[0], dict):
            msg = "Native profile requires exactly one reported measured batch"
            raise ValueError(msg)
        timing = batches[0].get("timing")
        if not isinstance(timing, dict):
            msg = "Native profile requires actual measured load timestamps"
            raise TypeError(msg)
        start, finish = timing.get("load_started_ns"), timing.get("load_finished_ns")
        if type(start) is not int or type(finish) is not int or not 0 < start < finish:
            msg = "Native profile load boundaries must be positive ordered nanosecond timestamps"
            raise ValueError(msg)
        if self.started_ns is None or self.finished_ns is None or self.started_ns >= self.finished_ns:
            msg = "Native profiler invocation boundaries are missing or invalid"
            raise ValueError(msg)
        overlap = max(0, min(finish, self.finished_ns) - max(start, self.started_ns))
        qualified = start <= self.started_ns < self.finished_ns <= finish
        payload.update(
            {
                "load_started_ns": start,
                "load_finished_ns": finish,
                "tool_load_overlap_ns": overlap,
                "tool_outside_load_ns": self.finished_ns - self.started_ns - overlap,
                "qualification": "qualified" if qualified else "unqualified",
                "qualification_reason": (
                    "Full tool invocation lies inside the measured load interval"
                    if qualified
                    else "Mixed or absent load overlap; profile cannot be treated as measured-load-only"
                ),
            },
        )
