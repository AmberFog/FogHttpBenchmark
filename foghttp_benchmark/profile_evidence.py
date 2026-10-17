__all__ = ("inspect_profile_evidence",)

import hashlib
from pathlib import Path
import re
from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.perf_evidence import (
    DEFAULT_PERF_SAMPLE_FREQUENCY_HZ,
    PERF_SAMPLE_FREQUENCIES_HZ,
    inspect_perf_text,
)


MAX_PROFILE_BYTES = 16 * 1024 * 1024
MAX_PERF_BYTES = 64 * 1024 * 1024
MONITORING_VERSION = (3, 12)
PERF_DURATION_S = 0.5


def _object(value: object) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _batches(child: JsonObject) -> list[JsonObject]:
    value = child.get("batches")
    return [_object(item) for item in value] if isinstance(value, list) else []


def _profile_file(
    evidence: JsonObject,
    result: JsonObject,
    root: Path,
    seen: set[Path],
    *,
    limit: int = MAX_PROFILE_BYTES,
) -> bytes:
    output, name, actual = result.get("output_dir"), evidence.get("relative_path"), evidence.get("path")
    if not isinstance(output, str) or not output:
        msg = "Profile case output directory is missing"
        raise ValueError(msg)
    case_directory = Path(output).resolve()
    if not case_directory.is_relative_to(root):
        msg = "Profile case output directory escapes the report directory"
        raise ValueError(msg)
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or Path(name).parts[0] != "profiles"
    ):
        msg = "Profile artifact requires a case-relative path"
        raise ValueError(msg)
    path = (case_directory / name).resolve()
    if not path.is_relative_to(case_directory) or not path.is_relative_to(root) or path in seen:
        msg = "Profile artifact escapes its owned case directory or is duplicated"
        raise ValueError(msg)
    if not isinstance(actual, str) or not Path(actual).is_absolute() or Path(actual).resolve() != path:
        msg = "Profile artifact absolute and case-relative paths differ"
        raise ValueError(msg)
    seen.add(path)
    size = evidence.get("size_bytes")
    if type(size) is not int or not 0 < size <= limit or path.stat().st_size != size:
        msg = f"Profile artifact size differs or exceeds the nonempty {limit // (1024 * 1024)} MiB bound"
        raise ValueError(msg)
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) != size or hashlib.sha256(content).hexdigest() != evidence.get("sha256"):
        msg = "Profile artifact checksum or read size differs"
        raise ValueError(msg)
    return content


def _load_bounds(batch: JsonObject, evidence: JsonObject) -> tuple[int, int]:
    timing = _object(batch.get("timing"))
    started, finished = timing.get("load_started_ns"), timing.get("load_finished_ns")
    if (
        not _positive_integer(started)
        or not _positive_integer(finished)
        or cast("int", started) >= cast("int", finished)
        or type(evidence.get("load_started_ns")) is not int
        or type(evidence.get("load_finished_ns")) is not int
        or evidence.get("load_started_ns") != started
        or evidence.get("load_finished_ns") != finished
    ):
        msg = "Profile artifact load timestamps differ from the actual measured batch"
        raise ValueError(msg)
    return cast("int", started), cast("int", finished)


def _python_evidence(result: JsonObject, child: JsonObject, root: Path) -> None:
    batches = _batches(child)
    if not batches:
        msg = "Declared cProfile measurement has no measured batches"
        raise ValueError(msg)
    if _object(child.get("warmup")).get("python_profile") is not None:
        msg = "Warmup must not contain an explicit Python load profile"
        raise ValueError(msg)
    seen: set[Path] = set()
    for batch in batches:
        evidence = _object(batch.get("python_profile"))
        if (
            evidence.get("profiler") != "cprofile"
            or evidence.get("status") != "ok"
            or not _positive_integer(result.get("client_pid"))
            or evidence.get("pid") != result.get("client_pid")
            or child.get("worker_pid") != result.get("client_pid")
            or not _positive_integer(evidence.get("thread_id"))
            or not isinstance(evidence.get("python_version"), str)
            or not evidence.get("python_version")
        ):
            msg = "Python profile identity/status/version is missing or differs from the owned client"
            raise ValueError(msg)
        started, finished = _load_bounds(batch, evidence)
        enabled, disabled = evidence.get("enabled_before_ns"), evidence.get("disabled_after_ns")
        if (
            not _positive_integer(enabled)
            or not _positive_integer(disabled)
            or cast("int", enabled) > started
            or cast("int", disabled) < finished
            or type(evidence.get("load_boundary_overhang_ns")) is not int
            or evidence.get("load_boundary_overhang_ns")
            != started - cast("int", enabled) + cast("int", disabled) - finished
        ):
            msg = "Python profiler enable/disable boundaries do not bracket the measured load"
            raise ValueError(msg)
        _profile_file(evidence, result, root, seen)
        _python_scope(evidence)


def _python_scope(evidence: JsonObject) -> None:
    version = str(evidence.get("python_version", "")).split(".")
    if len(version) < len(MONITORING_VERSION) or not all(part.isdigit() for part in version[:2]):
        msg = "Python profiler version must identify its monitoring scope"
        raise ValueError(msg)
    monitoring = tuple(int(part) for part in version[:2]) >= MONITORING_VERSION
    expected = (
        ("interpreter-monitoring", "unqualified-cross-thread-context")
        if monitoring
        else ("enabling-thread", "qualified-thread-scope")
    )
    if (
        (evidence.get("thread_scope"), evidence.get("attribution_qualification")) != expected
        or not _positive_integer(evidence.get("enabling_thread_id"))
        or evidence.get("enabling_thread_id") != evidence.get("thread_id")
    ):
        msg = "Python profiler thread scope/qualification differs from the recorded runtime"
        raise ValueError(msg)


def _native_identity(content: bytes, evidence: JsonObject, pid: int) -> None:
    text = content.decode("utf-8")
    process = re.search(r"^Process:\s+.+\[(\d+)\]\s*$", text, flags=re.MULTILINE)
    analysis = re.search(r"^Analysis of sampling .+ \(pid (\d+)\) every 1 millisecond\s*$", text, flags=re.MULTILINE)
    if (
        process is None
        or analysis is None
        or "Call graph:" not in text
        or int(process.group(1)) != pid
        or int(analysis.group(1)) != pid
        or evidence.get("pid_from_report") != pid
        or evidence.get("pid_from_analysis_header") != pid
    ):
        msg = "Native sample headers/call graph do not prove the owned target identity"
        raise ValueError(msg)


def _native_bounds(batch: JsonObject, evidence: JsonObject) -> None:
    started, finished = _load_bounds(batch, evidence)
    first, last = evidence.get("tool_started_ns"), evidence.get("tool_finished_ns")
    if not _positive_integer(first) or not _positive_integer(last) or cast("int", first) >= cast("int", last):
        msg = "Native profiler invocation timestamps are missing or unordered"
        raise ValueError(msg)
    first, last = cast("int", first), cast("int", last)
    overlap = max(0, min(finished, last) - max(started, first))
    qualified = started <= first < last <= finished
    if (
        type(evidence.get("tool_load_overlap_ns")) is not int
        or type(evidence.get("tool_outside_load_ns")) is not int
        or evidence.get("tool_load_overlap_ns") != overlap
        or evidence.get("tool_outside_load_ns") != last - first - overlap
        or evidence.get("qualification") != ("qualified" if qualified else "unqualified")
        or not isinstance(evidence.get("qualification_reason"), str)
        or not evidence.get("qualification_reason")
    ):
        msg = "Native profile qualification/overlap differs from actual load and invocation timestamps"
        raise ValueError(msg)


def _native_evidence(result: JsonObject, child: JsonObject, root: Path, backend: str) -> None:
    evidence = _object(result.get("native_profile"))
    role = "client" if backend == "sample-client" else "server"
    pid = result.get(f"{role}_pid")
    batches = _batches(child)
    if (
        evidence.get("profiler") != "sample"
        or evidence.get("status") != "ok"
        or type(evidence.get("returncode")) is not int
        or evidence.get("returncode") != 0
        or evidence.get("cleanup_interrupted") is not False
        or evidence.get("failures") != []
        or not _positive_integer(pid)
        or evidence.get("target_role") != role
        or evidence.get("target_pid") != pid
        or not _positive_integer(evidence.get("profiler_pid"))
        or evidence.get("profiler_pid") in {result.get("client_pid"), result.get("server_pid")}
        or type(evidence.get("sample_duration_s")) is not int
        or evidence.get("sample_duration_s") != 1
        or type(evidence.get("sample_interval_ms")) is not int
        or evidence.get("sample_interval_ms") != 1
        or len(batches) != 1
    ):
        msg = "Native profile identity/status/scope differs from the declared owned target"
        raise ValueError(msg)
    expected_command = ["/usr/bin/sample", str(pid), "1", "1", "-mayDie", "-file", evidence.get("path")]
    if evidence.get("command") != expected_command:
        msg = "Native profile command differs from its declared fixed tool/target/interval"
        raise ValueError(msg)
    _native_bounds(batches[0], evidence)
    content = _profile_file(evidence, result, root, set())
    _native_identity(content, evidence, cast("int", pid))


def _perf_evidence(result: JsonObject, child: JsonObject, root: Path, backend: str, frequency: int) -> None:
    evidence = _object(result.get("native_profile"))
    role = "client" if backend == "perf-client" else "server"
    pid, tool = result.get(f"{role}_pid"), evidence.get("tool_path")
    batches = _batches(child)
    if (
        evidence.get("profiler") != "perf"
        or evidence.get("status") != "ok"
        or type(evidence.get("returncode")) is not int
        or evidence.get("returncode") != 0
        or evidence.get("cleanup_interrupted") is not False
        or evidence.get("failures") != []
        or not _positive_integer(pid)
        or evidence.get("target_role") != role
        or evidence.get("target_pid") != pid
        or not _positive_integer(evidence.get("profiler_pid"))
        or evidence.get("profiler_pid") in {result.get("client_pid"), result.get("server_pid")}
        or evidence.get("sample_duration_s") != PERF_DURATION_S
        or type(evidence.get("sample_frequency_hz")) is not int
        or evidence.get("sample_frequency_hz") != frequency
        or len(batches) != 1
        or not isinstance(tool, str)
        or not Path(tool).is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("tool_sha256", "")))
        or not str(evidence.get("tool_version", "")).startswith("perf version ")
        or _object(evidence.get("python_clock")).get("implementation") != "clock_gettime(CLOCK_MONOTONIC)"
    ):
        msg = "Perf profile identity/status/tool/scope differs from the declared owned target"
        raise ValueError(msg)
    expected = [
        tool,
        "record",
        "--clockid",
        "mono",
        "-F",
        str(frequency),
        *(["--strict-freq"] if frequency != DEFAULT_PERF_SAMPLE_FREQUENCY_HZ else []),
        "-e",
        "cpu-clock:u",
        "--call-graph",
        "dwarf,8192",
        "-p",
        str(pid),
        "-o",
        evidence.get("path"),
        "--",
        "/usr/bin/sleep",
        "0.5",
    ]
    if evidence.get("command") != expected:
        msg = "Perf recording command differs from its declared tool/target/event/clock"
        raise ValueError(msg)
    seen: set[Path] = set()
    if not _profile_file(evidence, result, root, seen, limit=MAX_PERF_BYTES).startswith(b"PERFILE2"):
        msg = "Perf raw artifact does not identify the supported perf.data file format"
        raise ValueError(msg)
    artifacts = _object(evidence.get("text_artifacts"))
    if set(artifacts) != {"header", "script", "summary", "record_stderr"}:
        msg = "Perf recording requires complete bounded decoded text artifacts"
        raise ValueError(msg)
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
    for name, arguments in commands.items():
        if _object(artifacts[name]).get("command") != [tool, *arguments, "-i", evidence.get("path")]:
            msg = "Perf text decoding command differs from the declared owned raw recording"
            raise ValueError(msg)
    text = {
        name: _profile_file(_object(value), result, root, seen).decode("utf-8") for name, value in artifacts.items()
    }
    parsed = inspect_perf_text(pid=cast("int", pid), sample_frequency_hz=frequency, **text)
    if any(evidence.get(key) != value or type(evidence.get(key)) is not type(value) for key, value in parsed.items()):
        msg = "Perf sample identity/count/timestamps differ from decoded text artifacts"
        raise ValueError(msg)
    _perf_bounds(batches[0], evidence)


def _perf_bounds(batch: JsonObject, evidence: JsonObject) -> None:
    started, finished = _load_bounds(batch, evidence)
    first, last = evidence.get("tool_started_ns"), evidence.get("tool_finished_ns")
    if not _positive_integer(first) or not _positive_integer(last) or cast("int", first) >= cast("int", last):
        msg = "Perf invocation timestamps are missing or unordered"
        raise ValueError(msg)
    first, last = cast("int", first), cast("int", last)
    overlap = max(0, min(finished, last) - max(started, first))
    sample_first, sample_last = evidence.get("first_sample_ns"), evidence.get("last_sample_ns")
    qualified = (
        started <= first < last <= finished
        and type(sample_first) is int
        and type(sample_last) is int
        and started <= sample_first <= sample_last <= finished
    )
    if (
        type(evidence.get("tool_load_overlap_ns")) is not int
        or type(evidence.get("tool_outside_load_ns")) is not int
        or evidence.get("tool_load_overlap_ns") != overlap
        or evidence.get("tool_outside_load_ns") != last - first - overlap
        or evidence.get("qualification") != ("qualified" if qualified else "unqualified")
        or not isinstance(evidence.get("qualification_reason"), str)
        or not evidence.get("qualification_reason")
    ):
        msg = "Perf qualification/overlap differs from measured load and actual samples"
        raise ValueError(msg)


def inspect_profile_evidence(result: JsonObject, directory: Path) -> list[str]:
    child = _object(result.get("client_report"))
    attribution = _object(_object(child.get("config")).get("attribution"))
    backend = attribution.get("profiler", "none")
    frequency = attribution.get("perf_sample_frequency_hz", DEFAULT_PERF_SAMPLE_FREQUENCY_HZ)
    invalid_frequency = (
        type(frequency) is not int
        or frequency not in PERF_SAMPLE_FREQUENCIES_HZ
        or (frequency != DEFAULT_PERF_SAMPLE_FREQUENCY_HZ and backend not in ("perf-client", "perf-server"))
    )
    if backend == "none":
        unexpected = (
            invalid_frequency
            or result.get("native_profile") is not None
            or _object(child.get("warmup")).get("python_profile") is not None
            or any(batch.get("python_profile") is not None for batch in _batches(child))
        )
        return (
            ["Profile artifacts or nondefault sampling exist without a declared profiler backend"] if unexpected else []
        )
    if (
        invalid_frequency
        or not isinstance(backend, str)
        or backend
        not in {
            "cprofile",
            "sample-client",
            "sample-server",
            "perf-client",
            "perf-server",
        }
    ):
        return ["Unknown declared profiler backend or invalid perf sampling frequency"]
    label = attribution.get("profiler_label")
    if attribution.get("instrumentation") != "diagnostic" or not isinstance(label, str) or not label.strip():
        return ["Declared profiling requires diagnostic instrumentation and an explicit profiler label"]
    if (backend == "cprofile" and result.get("native_profile") is not None) or (
        backend != "cprofile" and any(batch.get("python_profile") is not None for batch in _batches(child))
    ):
        return ["Profile artifact conflicts with its declared profiler backend"]
    try:
        if backend == "cprofile":
            _python_evidence(result, child, directory.resolve())
        elif backend.startswith("perf-"):
            _perf_evidence(result, child, directory.resolve(), backend, cast("int", frequency))
        else:
            _native_evidence(result, child, directory.resolve(), backend)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return [f"Invalid profiler evidence: {error}"]
    return []
