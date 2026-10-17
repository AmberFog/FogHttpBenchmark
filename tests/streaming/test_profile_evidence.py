from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.profile_evidence import MAX_PROFILE_BYTES, inspect_profile_evidence
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from tests.isolation.perf_profile_support import DENSE_FREQUENCY_HZ, HEADER, SUMMARY
from tests.streaming import attribution_report_factory as factory


def profile_result(root: Path, *, backend: str = "cprofile", repeat: int = 1) -> dict[str, Any]:
    result = factory.result(repeat)
    child = result["client_report"]
    child["config"]["attribution"].update(
        instrumentation="diagnostic",
        profiler_label="profile-evidence-test",
        profiler=backend,
    )
    case = root / "isolated" / f"case-{repeat}"
    result["output_dir"] = str(case)
    profile = case / "profiles" / ("python-batch-001.pstats" if backend == "cprofile" else "native-sample.txt")
    profile.parent.mkdir(parents=True)
    batch = child["batches"][0]
    started, finished = batch["timing"]["load_started_ns"], batch["timing"]["load_finished_ns"]
    evidence = {
        "status": "ok",
        "path": str(profile),
        "relative_path": profile.relative_to(case).as_posix(),
        "load_started_ns": started,
        "load_finished_ns": finished,
    }
    if backend == "cprofile":
        content = b"opaque profiler fixture; validator must never deserialize pstats"
        evidence.update(
            profiler="cprofile",
            pid=result["client_pid"],
            thread_id=1,
            enabling_thread_id=1,
            thread_scope="interpreter-monitoring",
            attribution_qualification="unqualified-cross-thread-context",
            python_version="3.14.0",
            enabled_before_ns=started - 10,
            disabled_after_ns=finished + 20,
            load_boundary_overhang_ns=30,
        )
        batch["python_profile"] = evidence
    else:
        role = "client" if backend == "sample-client" else "server"
        pid = result[f"{role}_pid"]
        content = (
            f"Analysis of sampling Python (pid {pid}) every 1 millisecond\n"
            f"Process:         Python [{pid}]\nCall graph:\n    10 thread_start\n"
        ).encode()
        evidence.update(
            profiler="sample",
            target_role=role,
            target_pid=pid,
            profiler_pid=999,
            returncode=0,
            cleanup_interrupted=False,
            failures=[],
            sample_duration_s=1,
            sample_interval_ms=1,
            command=["/usr/bin/sample", str(pid), "1", "1", "-mayDie", "-file", str(profile)],
            tool_started_ns=started + 10,
            tool_finished_ns=finished - 10,
            tool_load_overlap_ns=finished - started - 20,
            tool_outside_load_ns=0,
            qualification="qualified",
            qualification_reason="Full invocation inside load",
            pid_from_report=pid,
            pid_from_analysis_header=pid,
        )
        result["native_profile"] = evidence
    profile.write_bytes(content)
    evidence.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    return result


def artifact(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("native_profile") or result["client_report"]["batches"][0]["python_profile"]


@pytest.mark.parametrize("fault", ["thread_scope", "attribution_qualification", "enabling_thread_id"])
def test_python_monitoring_cannot_claim_thread_local_attribution(tmp_path: Path, fault: str) -> None:
    result = profile_result(tmp_path)
    artifact(result).pop(fault)
    assert "scope/qualification" in inspect_profile_evidence(result, tmp_path)[0]


@pytest.mark.parametrize("backend", ["cprofile", "sample-client", "sample-server"])
def test_complete_owned_profiles_pass_file_identity_and_timing_checks(tmp_path: Path, backend: str) -> None:
    result = profile_result(tmp_path, backend=backend)

    assert inspect_profile_evidence(result, tmp_path) == []
    assert inspect_profile_evidence(result, Path(result["output_dir"])) == []


@pytest.mark.parametrize("backend", ["cprofile", "sample-client", "sample-server"])
@pytest.mark.parametrize("fault", ["missing", "corrupt", "wrong-size", "wrong-pid", "outside", "symlink"])
def test_profile_damage_identity_and_escaping_files_are_rejected(
    tmp_path: Path,
    backend: str,
    fault: str,
) -> None:
    root = tmp_path / "report"
    result = profile_result(root, backend=backend)
    evidence = artifact(result)
    path = Path(evidence["path"])
    if fault == "missing":
        path.unlink()
    elif fault == "corrupt":
        path.write_bytes(b"damaged".ljust(evidence["size_bytes"], b"x"))
    elif fault == "wrong-size":
        evidence["size_bytes"] += 1
    elif fault == "wrong-pid":
        evidence["pid" if backend == "cprofile" else "target_pid"] = result["parent_pid"]
    elif fault == "outside":
        evidence["relative_path"] = "../../outside.pstats"
    else:
        outside = tmp_path / "outside-profile"
        path.replace(outside)
        path.symlink_to(outside)

    assert inspect_profile_evidence(result, root)


def test_profiles_larger_than_the_explicit_limit_are_not_read(tmp_path: Path) -> None:
    result = profile_result(tmp_path)
    evidence = artifact(result)
    with Path(evidence["path"]).open("wb") as stream:
        stream.truncate(MAX_PROFILE_BYTES + 1)
    evidence["size_bytes"] = MAX_PROFILE_BYTES + 1

    assert "16 MiB" in inspect_profile_evidence(result, tmp_path)[0]


@pytest.mark.parametrize("fault", ["load", "enable", "disable", "overhang", "duplicate", "warmup", "no-batches"])
def test_python_profile_boundaries_and_measured_batch_coverage_cannot_be_fabricated(
    tmp_path: Path,
    fault: str,
) -> None:
    result = profile_result(tmp_path)
    child = result["client_report"]
    evidence = artifact(result)
    if fault == "load":
        evidence["load_finished_ns"] -= 1
    elif fault == "enable":
        evidence["enabled_before_ns"] = evidence["load_started_ns"] + 1
    elif fault == "disable":
        evidence["disabled_after_ns"] = evidence["load_finished_ns"] - 1
    elif fault == "overhang":
        evidence["load_boundary_overhang_ns"] = 0
    elif fault == "duplicate":
        child["batches"].append(deepcopy(child["batches"][0]))
    elif fault == "warmup":
        child["warmup"]["python_profile"] = deepcopy(evidence)
    else:
        child["batches"] = []

    assert inspect_profile_evidence(result, tmp_path)


@pytest.mark.parametrize("fault", ["headers", "qualification", "overlap", "exit", "command", "multiple-batches"])
def test_native_artifact_headers_and_actual_load_qualification_are_rechecked(tmp_path: Path, fault: str) -> None:
    result = profile_result(tmp_path, backend="sample-client")
    evidence = artifact(result)
    if fault == "headers":
        path = Path(evidence["path"])
        content = path.read_bytes().replace(b"Python [101]", b"Python [999]")
        path.write_bytes(content)
        evidence.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    elif fault == "qualification":
        evidence["qualification"] = "unqualified"
    elif fault == "overlap":
        evidence["tool_load_overlap_ns"] -= 1
    elif fault == "exit":
        evidence["returncode"] = False
    elif fault == "command":
        evidence["command"][1] = "999"
    else:
        result["client_report"]["batches"].append(deepcopy(result["client_report"]["batches"][0]))

    assert inspect_profile_evidence(result, tmp_path)


def test_truthful_mixed_native_profile_is_retained_as_unqualified(tmp_path: Path) -> None:
    result = profile_result(tmp_path, backend="sample-server")
    evidence = artifact(result)
    evidence.update(
        tool_started_ns=evidence["load_started_ns"] - 100,
        tool_load_overlap_ns=evidence["load_finished_ns"] - evidence["load_started_ns"] - 10,
        tool_outside_load_ns=100,
        qualification="unqualified",
        qualification_reason="Tool began before measured load; diagnostic mixed profile",
    )

    assert inspect_profile_evidence(result, tmp_path) == []


@pytest.mark.parametrize("backend", [None, [], {}, "unknown"])
def test_malformed_backend_is_reported_without_crashing_partial_report(tmp_path: Path, backend: object) -> None:
    result = profile_result(tmp_path)
    result["client_report"]["config"]["attribution"]["profiler"] = backend

    assert inspect_profile_evidence(result, tmp_path)


def test_declared_none_and_unrecorded_profiling_do_not_silently_mix(tmp_path: Path) -> None:
    assert inspect_profile_evidence(factory.result(1), tmp_path) == []
    result = profile_result(tmp_path)
    result["client_report"]["config"]["attribution"]["profiler"] = "none"

    assert inspect_profile_evidence(result, tmp_path)


@pytest.mark.parametrize("fault", ["missing", "corrupt"])
def test_loading_rechecks_profile_files_even_when_cached_raw_evidence_passed(
    tmp_path: Path,
    fault: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(
        factory.config(),
        attribution=AttributionConfig(
            instrumentation="diagnostic",
            profiler_label="profile-evidence-test",
            profiler="cprofile",
        ),
    )
    monkeypatch.setattr(factory, "config", lambda: config)
    values = [profile_result(tmp_path, repeat=repeat) for repeat in range(1, 4)]
    path = factory.write_report(tmp_path, values, with_provenance=True)
    initial = load_benchmark_report(path)
    assert initial.validity.status == "needs-rerun"
    assert "attribution_diagnostic_only" in {reason.code for reason in initial.validity.reasons}
    assert "attribution_raw_evidence_invalid" not in {reason.code for reason in initial.validity.reasons}
    damaged = Path(artifact(values[0])["path"])
    if fault == "missing":
        damaged.unlink()
    else:
        damaged.write_bytes(b"changed pstats")
    payload = json.loads(path.read_text())
    payload["metadata"]["raw_evidence_validation"] = {"status": "ok", "checked": 3, "aggregates_match": True}
    path.write_text(json.dumps(payload))

    report = load_benchmark_report(path)

    assert report.validity.status == "invalid"
    assert "attribution_raw_evidence_invalid" in {reason.code for reason in report.validity.reasons}


def perf_result(root: Path, *, backend: str = "perf-client", frequency: int = 499) -> dict[str, Any]:
    result = factory.result(1)
    child = result["client_report"]
    child["config"]["attribution"].update(
        instrumentation="diagnostic",
        profiler_label="perf-test",
        profiler=backend,
        perf_sample_frequency_hz=frequency,
    )
    case = root / "isolated" / "perf-case"
    result["output_dir"] = str(case)
    profiles = case / "profiles"
    profiles.mkdir(parents=True)
    start, finish = 1_000_000_000, 2_000_000_000
    child["batches"][0]["timing"].update(load_started_ns=start, load_finished_ns=finish)
    role = "client" if backend == "perf-client" else "server"
    pid = result[f"{role}_pid"]
    tool = "/owned/perf"

    def record(name: str, content: bytes) -> dict[str, Any]:
        path = profiles / name
        path.write_bytes(content)
        return {
            "path": str(path),
            "relative_path": f"profiles/{name}",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }

    evidence = record("perf.data", b"PERFILE2 bounded opaque fixture")
    script = (
        f"worker {pid}/{pid} 1.200000000: 2004008 cpu-clock:u: \n\t 1234 native_leaf (/owned/lib.so)\n\n"
        f"worker {pid}/{pid + 1} 1.300000000: 2004008 cpu-clock:u: \n\t 1234 native_leaf (/owned/lib.so)\n\n"
    )
    arguments = {
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
    contents = {
        "header": HEADER.replace("= 499", f"= {frequency}"),
        "script": script,
        "summary": SUMMARY,
        "record_stderr": "[ perf record: done ]\n",
    }
    artifacts = {name: record(f"perf-{name}.txt", content.encode()) for name, content in contents.items()}
    for name, command in arguments.items():
        artifacts[name]["command"] = [tool, *command, "-i", evidence["path"]]
    evidence.update(
        profiler="perf",
        status="ok",
        returncode=0,
        cleanup_interrupted=False,
        failures=[],
        target_role=role,
        target_pid=pid,
        profiler_pid=999,
        tool_path=tool,
        tool_version="perf version fixture-1",
        tool_sha256="a" * 64,
        sample_duration_s=0.5,
        sample_frequency_hz=frequency,
        python_clock={"implementation": "clock_gettime(CLOCK_MONOTONIC)", "resolution_s": 1e-9},
        command=[
            tool,
            "record",
            "--clockid",
            "mono",
            "-F",
            str(frequency),
            *(["--strict-freq"] if frequency == DENSE_FREQUENCY_HZ else []),
            "-e",
            "cpu-clock:u",
            "--call-graph",
            "dwarf,8192",
            "-p",
            str(pid),
            "-o",
            evidence["path"],
            "--",
            "/usr/bin/sleep",
            "0.5",
        ],
        text_artifacts=artifacts,
        load_started_ns=start,
        load_finished_ns=finish,
        tool_started_ns=start + 1,
        tool_finished_ns=finish - 1,
        tool_load_overlap_ns=finish - start - 2,
        tool_outside_load_ns=0,
        qualification="qualified",
        qualification_reason="Full measured load scope",
        sample_count=2,
        sample_pids=[pid],
        sample_tids=[pid, pid + 1],
        sample_period_sum=4_008_016,
        first_sample_ns=1_200_000_000,
        last_sample_ns=1_300_000_000,
        event="cpu-clock:u",
        event_type=1,
        event_config=0,
        exclude_kernel=True,
        exclude_hv=True,
        clockid=1,
        lost_samples=0,
    )
    result["native_profile"] = evidence
    return result


@pytest.mark.parametrize("backend", ["perf-client", "perf-server"])
@pytest.mark.parametrize("frequency", [499, 1999])
def test_perf_decoded_user_cpu_samples_are_owned_and_inside_measured_load(
    tmp_path: Path,
    backend: str,
    frequency: int,
) -> None:
    assert inspect_profile_evidence(perf_result(tmp_path, backend=backend, frequency=frequency), tmp_path) == []


def test_legacy_perf_receipt_without_frequency_option_retains_499_contract(tmp_path: Path) -> None:
    result = perf_result(tmp_path)
    result["client_report"]["config"]["attribution"].pop("perf_sample_frequency_hz")

    assert inspect_profile_evidence(result, tmp_path) == []


@pytest.mark.parametrize("damage", ["declared", "receipt", "argv", "strict-freq", "header", "reuse-as-legacy"])
def test_dense_perf_cannot_reuse_or_mismatch_other_frequency_evidence(tmp_path: Path, damage: str) -> None:
    result = perf_result(tmp_path, frequency=1999)
    evidence = artifact(result)
    if damage == "declared":
        result["client_report"]["config"]["attribution"]["perf_sample_frequency_hz"] = 499
    elif damage == "receipt":
        evidence["sample_frequency_hz"] = 499
    elif damage == "argv":
        evidence["command"][evidence["command"].index("-F") + 1] = "499"
    elif damage == "strict-freq":
        evidence["command"].remove("--strict-freq")
    elif damage == "reuse-as-legacy":
        result["client_report"]["config"]["attribution"].pop("perf_sample_frequency_hz")
    else:
        header = evidence["text_artifacts"]["header"]
        path = Path(header["path"])
        content = path.read_bytes().replace(b"= 1999", b"= 499")
        path.write_bytes(content)
        header.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))

    assert inspect_profile_evidence(result, tmp_path)


@pytest.mark.parametrize("damage", ["kernel", "clock", "frequency", "pid", "lost", "dropped-line", "period", "summary"])
@pytest.mark.parametrize("frequency", [499, 1999])
def test_perf_decoded_contract_is_rechecked_even_after_text_is_resigned(
    tmp_path: Path,
    damage: str,
    frequency: int,
) -> None:
    result = perf_result(tmp_path, frequency=frequency)
    evidence = artifact(result)
    key = "header" if damage in {"kernel", "clock", "frequency"} else "summary" if damage == "summary" else "script"
    text = evidence["text_artifacts"][key]
    path = Path(text["path"])
    content = path.read_text()
    if damage == "kernel":
        content = content.replace("exclude_kernel = 1", "exclude_kernel = 0")
    elif damage == "clock":
        content = content.replace("clockid = 1", "clockid = 0")
    elif damage == "frequency":
        content = content.replace(f"= {frequency}", "= 199")
    elif damage == "pid":
        content = content.replace("101/101", "999/101")
    elif damage == "lost":
        content += "PERF_RECORD_LOST 2\n"
    elif damage == "dropped-line":
        content = content.replace("worker 101/101", "worker 101")
    elif damage == "period":
        content = content.replace("2004008", "10", 1)
    else:
        content = content.replace("Samples: 2", "Samples: 3")
    path.write_text(content)
    text.update(sha256=hashlib.sha256(content.encode()).hexdigest(), size_bytes=path.stat().st_size)

    assert inspect_profile_evidence(result, tmp_path)


@pytest.mark.parametrize("damage", ["missing-sidecar", "binary", "scope", "command", "tool", "checksum"])
@pytest.mark.parametrize("frequency", [499, 1999])
def test_perf_raw_artifact_and_tool_evidence_cannot_be_missing_or_inconsistent(
    tmp_path: Path,
    damage: str,
    frequency: int,
) -> None:
    result = perf_result(tmp_path, frequency=frequency)
    evidence = artifact(result)
    if damage == "missing-sidecar":
        evidence["text_artifacts"].pop("header")
    elif damage == "binary":
        path = Path(evidence["path"])
        content = b"incorrect raw artifact"
        path.write_bytes(content)
        evidence.update(sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    elif damage == "scope":
        evidence["load_finished_ns"] = evidence["first_sample_ns"] - 1
    elif damage == "command":
        evidence["text_artifacts"]["script"]["command"].remove("--ns")
    elif damage == "tool":
        evidence["tool_sha256"] = ""
    else:
        evidence["text_artifacts"]["script"]["sha256"] = "a" * 64

    assert inspect_profile_evidence(result, tmp_path)
