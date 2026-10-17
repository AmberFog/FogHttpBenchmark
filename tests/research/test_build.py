from contextlib import suppress
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

import psutil
import pytest

from foghttp_benchmark import provenance, research_build


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("Darwin", "arm64", "aarch64-apple-darwin"),
        ("Linux", "aarch64", "aarch64-unknown-linux-gnu"),
    ],
)
def test_native_host_target_is_recorded_and_passed_to_the_release_build(
    system: str,
    machine: str,
    target: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(research_build.platform, "system", lambda: system)
    monkeypatch.setattr(research_build.platform, "machine", lambda: machine)
    (tmp_path / "logs").mkdir()
    responses = {
        "rustc-path": str(tmp_path / "toolchain" / "bin" / "rustc"),
        "rustc": f"rustc 1.95.0\nrelease: 1.95.0\nhost: {target}\n",
        "cargo": "cargo 1.95.0 (fixture)",
        "uv": "uv 0.12.17",
        "maturin": "maturin 1.14.1",
        "build-packages": "{}",
    }

    def run(command: list[str], **kwargs: Any) -> str:
        if kwargs["name"] == "foghttp-build":
            text = "release opt-level=3 [optimized]"
            (tmp_path / "logs" / "foghttp-build.log").write_text(text, encoding="utf-8")
            return text
        return responses.get(kwargs["name"], "")

    monkeypatch.setattr(research_build, "_run", run)
    environment = {"PATH": os.environ["PATH"]}
    selected = research_build._host_build_target()  # noqa: SLF001 - native host allowlist contract.
    toolchain = research_build._toolchain(tmp_path, environment, selected)  # noqa: SLF001 - compiler host verification.
    build = research_build._build_foghttp(  # noqa: SLF001 - external release command and recorded target contract.
        tmp_path,
        Path(sys.executable),
        environment,
        {"checkout": str(tmp_path / "source")},
        toolchain,
    )

    assert selected == build["target"] == build["toolchain"]["target"] == target
    command = build["command"]
    assert command[command.index("--target") + 1] == target
    assert "--release" in command
    assert "--locked" in command
    assert build["profile_overrides"] == {}
    assert build["environment"]["RUSTFLAGS"] is None


@pytest.mark.parametrize(("system", "machine"), [("Darwin", "x86_64"), ("Linux", "arm64"), ("Windows", "aarch64")])
def test_unsupported_host_fails_before_creating_research_output(
    system: str,
    machine: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})
    monkeypatch.setattr(research_build.platform, "system", lambda: system)
    monkeypatch.setattr(research_build.platform, "machine", lambda: machine)
    output = tmp_path / "research"

    with pytest.raises(ValueError, match="Unsupported native research build host"):
        research_build.prepare_research_environment(output, Path(sys.executable), tmp_path)

    assert not output.exists()


@pytest.mark.parametrize(
    ("target", "reported_host", "reported_version"),
    [
        ("aarch64-apple-darwin", "aarch64-unknown-linux-gnu", "1.95.0"),
        ("aarch64-unknown-linux-gnu", "aarch64-apple-darwin", "1.95.0"),
        ("aarch64-unknown-linux-gnu", "aarch64-unknown-linux-gnu", "1.94.0"),
    ],
)
def test_mismatched_compiler_host_or_version_cannot_select_a_cross_build(
    target: str,
    reported_host: str,
    reported_version: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def run(command: list[str], **kwargs: Any) -> str:
        if kwargs["name"] == "rustc-path":
            return str(tmp_path / "toolchain" / "bin" / "rustc")
        assert kwargs["name"] == "rustc"
        return f"rustc {reported_version}\nrelease: {reported_version}\nhost: {reported_host}\n"

    monkeypatch.setattr(research_build, "_run", run)

    with pytest.raises(ValueError, match=f"Rust 1.95.0 on {target}"):
        research_build._toolchain(tmp_path, {"PATH": os.environ["PATH"]}, target)  # noqa: SLF001 - no cross-build policy.


@pytest.mark.parametrize(
    "name",
    [
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CARGO_PROFILE_RELEASE_OPT_LEVEL",
        "RUSTC_WRAPPER",
        "PYO3_CONFIG_FILE",
        "PYTHONPATH",
        "DYLD_INSERT_LIBRARIES",
        "CC",
        "MACOSX_DEPLOYMENT_TARGET",
        "HOST_CC",
        "TARGET_CFLAGS",
        "CC_aarch64_apple_darwin",
    ],
)
def test_unrecorded_build_and_loader_overrides_fail_before_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"], name: "external-value"})
    output = tmp_path / "research"

    with pytest.raises(ValueError, match=name):
        research_build.prepare_research_environment(output, Path(sys.executable), tmp_path)

    assert not output.exists()


def test_existing_output_is_not_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})
    stale = tmp_path / "old.whl"
    stale.write_bytes(b"existing artifact")

    with pytest.raises(FileExistsError):
        research_build.prepare_research_environment(tmp_path, Path(sys.executable), tmp_path)

    assert stale.read_bytes() == b"existing artifact"


@pytest.mark.parametrize("observed", ["", f"{'a' * 40}\trefs/heads/release/0.4.2"])
def test_changed_or_missing_branch_cannot_select_a_new_baseline(observed: str) -> None:
    with pytest.raises(ValueError, match="explicit baseline decision"):
        research_build._check_branch_tip(observed)  # noqa: SLF001 - pinned baseline refusal contract.


@pytest.mark.parametrize("branch", ["release/0.4.2", "release/reviewed-next-baseline"])
def test_source_is_a_fresh_detached_exact_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    branch: str,
) -> None:
    repository = tmp_path / "origin"
    repository.mkdir()
    subprocess.run(  # noqa: S603
        ["git", "init", "--initial-branch", branch, str(repository)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    (repository / "pyproject.toml").write_text('[project]\nversion = "0.4.2"\n', encoding="utf-8")
    (repository / "Cargo.toml").write_text('[package]\nversion = "0.4.2"\n', encoding="utf-8")
    (repository / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True, capture_output=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607 - temporary local Git fixture.
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        check=True,
        capture_output=True,
    )
    sha = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()  # noqa: S603, S607
    (repository / "old-native.so").write_bytes(b"not in selected revision")
    baseline = replace(
        research_build.FOGHTTP_BASELINE,
        repository=str(repository),
        ref=f"refs/heads/{branch}",
        sha=sha,
    )
    monkeypatch.setattr(research_build, "FOGHTTP_BASELINE", baseline)
    monkeypatch.setattr(provenance, "FOGHTTP_BASELINE", baseline)
    output = tmp_path / "research"
    (output / "logs").mkdir(parents=True)

    source = research_build._source_checkout(output, dict(os.environ))  # noqa: SLF001 - real Git boundary.

    assert source["sha"] == sha == source["tip"]
    assert source["ref"] == f"refs/heads/{branch}"
    assert source["dirty"] is False
    checkout = Path(source["checkout"])
    assert not (checkout / "old-native.so").exists()
    assert subprocess.check_output(["git", "-C", str(checkout), "branch", "--show-current"], text=True).strip() == ""  # noqa: S603, S607
    provenance.verify_source(source, check_remote=True)


def test_ambiguous_wheels_fail_instead_of_reusing_one(tmp_path: Path) -> None:
    (tmp_path / "foghttp-first.whl").write_bytes(b"one")
    (tmp_path / "foghttp-second.whl").write_bytes(b"two")

    with pytest.raises(ValueError, match="exactly one"):
        research_build._single_wheel(tmp_path, "foghttp")  # noqa: SLF001 - stale artifact refusal contract.


def test_checksum_inventory_covers_retained_evidence_only(tmp_path: Path) -> None:
    names = (
        "manifest.json",
        "build-requirements.txt",
        "dependencies.txt",
        "wheels/foghttp.whl",
        "logs/build.log",
    )
    for name in (*names, "venv/private-file", "cargo-target/transient"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")

    research_build._write_checksum_inventory(tmp_path)  # noqa: SLF001 - retained evidence checksum contract.

    lines = (tmp_path / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    assert lines == [f"{hashlib.sha256(name.encode()).hexdigest()}  {name}" for name in sorted(names)]


def test_failed_command_preserves_diagnostic_log(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="exit 7"):
        research_build._run(  # noqa: SLF001 - failure diagnostics at the external command boundary.
            [sys.executable, "-I", "-c", "import sys; print('diagnostic'); sys.exit(7)"],
            directory=tmp_path,
            environment=dict(os.environ),
            logs=tmp_path,
            name="failed",
        )

    assert "diagnostic" in (tmp_path / "failed.log").read_text(encoding="utf-8")
    assert "failed.log" in (tmp_path / "commands.jsonl").read_text(encoding="utf-8")


def test_timeout_kills_owned_subprocess_tree(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child-pid"
    child_script = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(child_pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    parent_script = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-I','-c',{child_script!r}]); "
        "print('spawned',flush=True); time.sleep(30)"
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            research_build._run(  # noqa: SLF001 - subprocess ownership on timeout is an external boundary.
                [sys.executable, "-I", "-c", parent_script],
                directory=tmp_path,
                environment=dict(os.environ),
                logs=tmp_path,
                name="timeout",
                timeout=1,
            )

        assert "spawned" in (tmp_path / "timeout.log").read_text(encoding="utf-8")
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while process_is_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not process_is_alive(child_pid)
    finally:
        if child_pid_file.exists():
            with suppress(ProcessLookupError):
                os.kill(int(child_pid_file.read_text(encoding="utf-8")), signal.SIGKILL)


def process_is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
