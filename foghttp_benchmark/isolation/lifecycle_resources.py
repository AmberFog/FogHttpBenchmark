__all__ = ("LifecycleResourceSampler", "ProcessResourceProbe")

from dataclasses import asdict, dataclass, field
import importlib
from itertools import pairwise
import statistics
import subprocess
import time
from typing import TYPE_CHECKING, Any, cast

from foghttp_benchmark.models import JsonObject


if TYPE_CHECKING:
    from collections.abc import Callable


EXIT_CONFIRMATION_TIMEOUT_S = 0.05


@dataclass(slots=True)
class ResourceSample:
    role: str
    pid: int
    monotonic_ns: int
    phase: str
    rss_bytes: int | None = None
    threads: int | None = None
    fds: int | None = None
    cpu_user_s: float | None = None
    cpu_system_s: float | None = None
    probe_duration_ns: int = 0
    process_terminated: bool = False
    termination_reason: str | None = None
    unavailable: dict[str, str] = field(default_factory=dict)

    def payload(self) -> JsonObject:
        return cast("JsonObject", asdict(self))


class ProcessResourceProbe:
    def __init__(
        self,
        role: str,
        pid: int,
        *,
        completion: "Callable[[], int | None] | None" = None,
        wait_for_exit: "Callable[[float], int] | None" = None,
    ) -> None:
        self.role = role
        self.pid = pid
        self.completion = completion
        self.wait_for_exit = wait_for_exit
        self.process: Any | None = None
        self.reason = ""
        self.no_such_process: type[Exception] = ProcessLookupError
        self.initially_exited = False
        try:
            psutil = importlib.import_module("psutil")
            self.no_such_process = psutil.NoSuchProcess
            self.process = psutil.Process(pid)
        except Exception as error:  # noqa: BLE001 - unavailable OS probes must retain a reason.
            self.reason = f"{type(error).__name__}: {error}"
            self.initially_exited = isinstance(error, self.no_such_process)

    def confirm_termination(self, sample: ResourceSample, *, rss_exit_candidate: bool) -> None:
        if not rss_exit_candidate or self.completion is None:
            return
        returncode = self.completion()
        if returncode is None and self.wait_for_exit is not None:
            try:
                returncode = self.wait_for_exit(EXIT_CONFIRMATION_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return
        if returncode is not None:
            sample.process_terminated = True
            sample.termination_reason = f"Owned child exit around RSS probe; confirmed return code {returncode}"

    def sample(self, phase: str) -> ResourceSample:
        sample = ResourceSample(self.role, self.pid, time.monotonic_ns(), phase)
        process = self.process
        if process is None:
            metrics = ("rss_bytes", "threads", "fds", "cpu_user_s", "cpu_system_s")
            sample.unavailable = dict.fromkeys(metrics, self.reason)
            self.confirm_termination(sample, rss_exit_candidate=self.initially_exited)
            sample.probe_duration_ns = time.monotonic_ns() - sample.monotonic_ns
            return sample
        rss_probe_exited = False
        getters: dict[str, Callable[[], int]] = {
            "rss_bytes": lambda: int(process.memory_info().rss),
            "threads": lambda: int(process.num_threads()),
            "fds": lambda: int(process.num_fds()),
        }
        for metric, getter in getters.items():
            try:
                setattr(sample, metric, getter())
            except Exception as error:  # noqa: BLE001 - each metric is independently optional on supported hosts.
                sample.unavailable[metric] = f"{type(error).__name__}: {error}"
                if metric == "rss_bytes":
                    rss_probe_exited = isinstance(error, self.no_such_process)
        try:
            cpu = process.cpu_times()
            sample.cpu_user_s = float(cpu.user)
            sample.cpu_system_s = float(cpu.system)
        except Exception as error:  # noqa: BLE001 - unavailable CPU is null, never a fabricated zero delta.
            reason = f"{type(error).__name__}: {error}"
            sample.unavailable.update({"cpu_user_s": reason, "cpu_system_s": reason})
        if sample.rss_bytes == 0:
            sample.rss_bytes = None
            sample.unavailable["rss_bytes"] = "RSS probe returned zero; live process memory is unavailable"
            rss_probe_exited = True
        self.confirm_termination(sample, rss_exit_candidate=rss_probe_exited)
        sample.probe_duration_ns = time.monotonic_ns() - sample.monotonic_ns
        return sample


class LifecycleResourceSampler:
    def __init__(self, *, interval_s: float, max_samples: int, rss_ceiling_bytes: int) -> None:
        self.interval_s = interval_s
        self.max_samples = max_samples
        self.rss_ceiling_bytes = rss_ceiling_bytes
        self.probes: dict[str, ProcessResourceProbe] = {}
        self.samples: list[JsonObject] = []
        self.phases: list[JsonObject] = []
        self.cpu_phase_deltas: list[JsonObject] = []
        self.previous_phase: dict[str, ResourceSample] = {}
        self.peaks: dict[str, JsonObject] = {}
        self.truncated = False

    def attach(
        self,
        role: str,
        pid: int,
        *,
        completion: "Callable[[], int | None] | None" = None,
        wait_for_exit: "Callable[[float], int] | None" = None,
    ) -> None:
        self.probes[role] = ProcessResourceProbe(role, pid, completion=completion, wait_for_exit=wait_for_exit)
        self.peaks[role] = {"rss_bytes": None, "threads": None, "fds": None}

    def sample(self, phase: str) -> tuple[dict[str, ResourceSample], list[str]]:
        observations = {role: probe.sample(phase) for role, probe in self.probes.items()}
        failures: list[str] = []
        for role, sample in observations.items():
            if len(self.samples) < self.max_samples:
                self.samples.append(sample.payload())
            elif not self.truncated:
                self.truncated = True
                failures.append("Resource sample cap reached; incomplete series")
            for metric in ("rss_bytes", "threads", "fds"):
                value = getattr(sample, metric)
                previous = self.peaks[role][metric]
                if value is not None:
                    self.peaks[role][metric] = value if previous is None else max(value, cast("int", previous))
            if sample.rss_bytes is not None and sample.rss_bytes > self.rss_ceiling_bytes:
                failures.append(f"{role} PID {sample.pid} exceeded RSS ceiling {self.rss_ceiling_bytes} bytes")
            elif sample.rss_bytes is None and not sample.process_terminated:
                reason = sample.unavailable["rss_bytes"]
                failures.append(f"Cannot enforce RSS ceiling for {role} PID {sample.pid}: {reason}")
        return observations, failures

    def mark(self, marker: JsonObject) -> list[str]:
        phase = cast("str", marker["phase"])
        observations, failures = self.sample(phase)
        record: JsonObject = {"sequence": marker["sequence"], "phase": phase, "worker": marker}
        for role, sample in observations.items():
            record[role] = sample.payload()
            previous = self.previous_phase.get(role)
            if previous is not None:
                self.cpu_phase_deltas.append(cpu_delta(previous, sample))
            self.previous_phase[role] = sample
        self.phases.append(record)
        return failures

    def payload(self) -> JsonObject:
        return {
            "scope": "separate-client-server-processes",
            "sample_interval_s": self.interval_s,
            "max_samples": self.max_samples,
            "rss_ceiling_bytes": self.rss_ceiling_bytes,
            "units": {"rss_bytes": "bytes", "cpu_user_s": "seconds", "cpu_system_s": "seconds"},
            "sampling_location": "parent-process-outside-client-event-loop",
            "peak_limitation": "Sampled peaks can miss events shorter than the observed sampling intervals",
            "samples": self.samples,
            "phases": self.phases,
            "cpu_phase_deltas": self.cpu_phase_deltas,
            "sampled_peaks": self.peaks,
            "observed_intervals_s": self.observed_intervals(),
            "rss_ceiling_scope": "Observed per-PID samples; peaks between probes may exceed the declared ceiling",
            "probe_overhead": "Per-sample probe_duration_ns records parent-side probe cost; it is not zero",
            "exit_confirmation_timeout_s": EXIT_CONFIRMATION_TIMEOUT_S,
            "truncated": self.truncated,
        }

    def observed_intervals(self) -> JsonObject:
        result: JsonObject = {}
        for role in self.probes:
            timestamps = [cast("int", item["monotonic_ns"]) for item in self.samples if item["role"] == role]
            intervals = [(end - start) / 1_000_000_000 for start, end in pairwise(timestamps)]
            result[role] = {
                "count": len(intervals),
                "min": min(intervals) if intervals else None,
                "max": max(intervals) if intervals else None,
                "median": statistics.median(intervals) if intervals else None,
                "includes_phase_barrier_samples": True,
            }
        return result


def cpu_delta(before: ResourceSample, after: ResourceSample) -> JsonObject:
    result: JsonObject = {
        "role": after.role,
        "pid": after.pid,
        "from_phase": before.phase,
        "to_phase": after.phase,
        "user_s": None,
        "system_s": None,
    }
    unavailable: dict[str, str] = {}
    for output, attribute in (("user_s", "cpu_user_s"), ("system_s", "cpu_system_s")):
        start = getattr(before, attribute)
        end = getattr(after, attribute)
        if start is None or end is None:
            unavailable[output] = before.unavailable.get(attribute) or after.unavailable.get(attribute, "Unavailable")
        elif end < start:
            unavailable[output] = "CPU counter decreased; phase delta is unavailable"
        else:
            result[output] = end - start
    result["unavailable"] = unavailable
    return result
