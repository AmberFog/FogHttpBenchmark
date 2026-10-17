__all__ = ("prepare_research_environment",)

from contextlib import suppress
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tomllib
from typing import Any

from foghttp_benchmark.provenance import capture_harness, git_bytes, git_text, inspect_distribution_wheel, inspect_wheel
from foghttp_benchmark.research_baseline import FOGHTTP_BASELINE


OVERRIDE_PREFIXES = ("CARGO_", "RUST", "PYO3_", "MATURIN_", "PYTHON", "DYLD_", "LD_")
OVERRIDE_NAMES = frozenset(
    {
        "CC",
        "CXX",
        "AR",
        "LD",
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "ARCHFLAGS",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "LIBRARY_PATH",
    },
)
CC_OVERRIDE_PREFIXES = ("CC_", "CXX_", "AR_", "CFLAGS_", "CXXFLAGS_", "CPPFLAGS_", "LDFLAGS_")
CC_OVERRIDE_NAMES = frozenset(
    f"{scope}_{name}"
    for scope in ("HOST", "TARGET")
    for name in ("CC", "CXX", "AR", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS")
)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _host_build_target() -> str:
    host = (platform.system(), platform.machine())
    targets = {
        ("Darwin", "arm64"): "aarch64-apple-darwin",
        ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    }
    if host not in targets:
        msg = f"Unsupported native research build host: {host[0]}/{host[1]}"
        raise ValueError(msg)
    return targets[host]


def _build_environment() -> dict[str, str]:
    rejected = sorted(
        name
        for name in os.environ
        if name.startswith((*OVERRIDE_PREFIXES, *CC_OVERRIDE_PREFIXES)) or name in OVERRIDE_NAMES | CC_OVERRIDE_NAMES
    )
    if rejected:
        msg = f"Unrecorded compiler, loader or Python overrides: {', '.join(rejected)}"
        raise ValueError(msg)
    environment = {name: value for name, value in os.environ.items() if not name.startswith("UV_")}
    environment.pop("VIRTUAL_ENV", None)
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "NO_COLOR": "1"})
    return environment


def _run(
    command: list[str],
    *,
    directory: Path,
    environment: dict[str, str],
    logs: Path,
    name: str,
    timeout: int = 300,
) -> str:
    log = logs / f"{name}.log"
    with (logs / "commands.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"command": command, "cwd": str(directory), "log": str(log), "timeout_s": timeout}) + "\n",
        )
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(  # noqa: S603 - explicit commands; no shell interpolation.
            command,
            cwd=directory,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise
    if returncode:
        msg = f"Command failed with exit {returncode}; see {log}"
        raise RuntimeError(msg)
    return log.read_text(encoding="utf-8").strip()


def _single_wheel(directory: Path, prefix: str) -> Path:
    wheels = list(directory.glob(f"{prefix}-*.whl"))
    if len(wheels) != 1:
        msg = f"Expected exactly one {prefix} wheel in {directory}, found {len(wheels)}"
        raise ValueError(msg)
    return wheels[0].resolve()


def _write_checksum_inventory(output: Path) -> None:
    paths = [output / name for name in ("manifest.json", "build-requirements.txt", "dependencies.txt")]
    paths.extend((output / "wheels").glob("*.whl"))
    paths.extend(path for path in (output / "logs").iterdir() if path.is_file())
    inventory = "".join(f"{_sha256(path)}  {path.relative_to(output)}\n" for path in sorted(paths))
    (output / "checksums.sha256").write_text(inventory, encoding="utf-8")


def _check_branch_tip(observed: str) -> None:
    tip = observed.split(maxsplit=1)[0] if observed.split() else ""
    if tip != FOGHTTP_BASELINE.sha:
        msg = (
            f"Release branch moved: expected {FOGHTTP_BASELINE.sha}, observed {tip}; "
            "record an explicit baseline decision"
        )
        raise ValueError(msg)


def _source_checkout(output: Path, environment: dict[str, str]) -> dict[str, Any]:
    logs = output / "logs"
    _check_branch_tip(
        _run(
            ["git", "ls-remote", FOGHTTP_BASELINE.repository, FOGHTTP_BASELINE.ref],
            directory=output,
            environment=environment,
            logs=logs,
            name="remote-before",
        ),
    )
    checkout = output / "foghttp-source"
    _run(
        [
            "git",
            "clone",
            "--no-checkout",
            "--single-branch",
            "--branch",
            FOGHTTP_BASELINE.branch,
            FOGHTTP_BASELINE.repository,
            str(checkout),
        ],
        directory=output,
        environment=environment,
        logs=logs,
        name="clone",
        timeout=600,
    )
    local_tip = _run(
        ["git", "rev-parse", FOGHTTP_BASELINE.tracking_ref],
        directory=checkout,
        environment=environment,
        logs=logs,
        name="fetched-tip",
    )
    _check_branch_tip(local_tip)
    _run(
        ["git", "merge-base", "--is-ancestor", FOGHTTP_BASELINE.sha, FOGHTTP_BASELINE.tracking_ref],
        directory=checkout,
        environment=environment,
        logs=logs,
        name="ancestor",
    )
    _run(
        ["git", "checkout", "--detach", FOGHTTP_BASELINE.sha],
        directory=checkout,
        environment=environment,
        logs=logs,
        name="checkout",
    )
    dirty = _run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        directory=checkout,
        environment=environment,
        logs=logs,
        name="source-status",
    )
    if dirty:
        msg = "FogHTTP source checkout is dirty"
        raise ValueError(msg)
    project = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = tomllib.loads((checkout / "Cargo.toml").read_text(encoding="utf-8"))
    if (
        project["project"]["version"] != FOGHTTP_BASELINE.version
        or cargo["package"]["version"] != FOGHTTP_BASELINE.version
    ):
        msg = f"Source metadata does not describe FogHTTP {FOGHTTP_BASELINE.version}"
        raise ValueError(msg)
    if "profile" in cargo:
        msg = "A custom Cargo profile requires an explicit reviewed baseline"
        raise ValueError(msg)
    for ancestor in (checkout, *checkout.parents):
        if any((ancestor / ".cargo" / name).exists() for name in ("config", "config.toml")):
            msg = f"Unrecorded Cargo configuration under {ancestor}"
            raise ValueError(msg)
    return {
        "repository": FOGHTTP_BASELINE.repository,
        "ref": FOGHTTP_BASELINE.ref,
        "tip": local_tip,
        "sha": FOGHTTP_BASELINE.sha,
        "tree": _run(
            ["git", "rev-parse", "HEAD^{tree}"],
            directory=checkout,
            environment=environment,
            logs=logs,
            name="source-tree",
        ),
        "checkout": str(checkout),
        "cargo_lock_sha256": _sha256(checkout / "Cargo.lock"),
        "pyproject_sha256": _sha256(checkout / "pyproject.toml"),
        "dirty": False,
    }


def _toolchain(output: Path, environment: dict[str, str], target: str) -> dict[str, str]:
    logs = output / "logs"
    rustc_path = Path(
        _run(["rustup", "which", "rustc"], directory=output, environment=environment, logs=logs, name="rustc-path"),
    )
    environment.update(
        {
            "PATH": str(rustc_path.parent) + os.pathsep + environment["PATH"],
            "RUSTC": str(rustc_path),
            "RUSTDOC": str(rustc_path.with_name("rustdoc")),
            "RUSTUP_TOOLCHAIN": str(rustc_path.parent.parent),
        },
    )
    rustc = _run(["rustc", "-Vv"], directory=output, environment=environment, logs=logs, name="rustc")
    if f"release: {FOGHTTP_BASELINE.rust_version}\n" not in rustc + "\n" or f"host: {target}\n" not in rustc + "\n":
        msg = f"This baseline requires Rust {FOGHTTP_BASELINE.rust_version} on {target}"
        raise ValueError(msg)
    cargo = _run(["cargo", "-V"], directory=output, environment=environment, logs=logs, name="cargo")
    if not cargo.startswith(f"cargo {FOGHTTP_BASELINE.rust_version} "):
        msg = f"Expected Cargo {FOGHTTP_BASELINE.rust_version}, found {cargo}"
        raise ValueError(msg)
    return {
        "target": target,
        "rustc": rustc,
        "cargo": cargo,
        "uv": _run(["uv", "--version"], directory=output, environment=environment, logs=logs, name="uv"),
    }


def _build_foghttp(
    output: Path,
    python: Path,
    environment: dict[str, str],
    source: dict[str, Any],
    toolchain: dict[str, str],
) -> dict[str, Any]:
    logs = output / "logs"
    build_python = output / "build-env" / "bin" / "python"
    _run(
        ["uv", "venv", "--python", str(python), str(build_python.parent.parent)],
        directory=output,
        environment=environment,
        logs=logs,
        name="build-venv",
    )
    (output / "build-requirements.txt").write_text(
        "\n".join(FOGHTTP_BASELINE.build_requirements) + "\n",
        encoding="utf-8",
    )
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(build_python),
            "--only-binary",
            ":all:",
            *FOGHTTP_BASELINE.build_requirements,
        ],
        directory=output,
        environment=environment,
        logs=logs,
        name="build-tools-install",
    )
    toolchain["maturin"] = _run(
        [str(build_python), "-I", "-m", "maturin", "--version"],
        directory=output,
        environment=environment,
        logs=logs,
        name="maturin",
    )
    if toolchain["maturin"] != f"maturin {FOGHTTP_BASELINE.maturin_version}":
        msg = "Unexpected maturin version in the isolated build environment"
        raise ValueError(msg)
    inventory_script = (
        "import importlib.metadata,json; "
        "print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()},sort_keys=True))"
    )
    build_packages = _run(
        [
            str(build_python),
            "-I",
            "-c",
            inventory_script,
        ],
        directory=output,
        environment=environment,
        logs=logs,
        name="build-packages",
    )
    environment.update({"CARGO_HOME": str(output / "cargo-home"), "CARGO_TARGET_DIR": str(output / "cargo-target")})
    command = [
        str(build_python),
        "-I",
        "-m",
        "maturin",
        "build",
        "--release",
        "--locked",
        "--interpreter",
        str(python),
        "--target",
        toolchain["target"],
        "--out",
        str(output / "wheels"),
        "-vv",
        "--color",
        "never",
    ]
    log_text = _run(
        command,
        directory=Path(source["checkout"]),
        environment=environment,
        logs=logs,
        name="foghttp-build",
        timeout=1800,
    )
    if "opt-level=3" not in log_text or "[optimized]" not in log_text or "release" not in log_text:
        msg = "Build log does not prove an optimized release profile"
        raise ValueError(msg)
    return {
        "profile": "release",
        "command": command,
        "log": str(logs / "foghttp-build.log"),
        "log_sha256": _sha256(logs / "foghttp-build.log"),
        "toolchain": toolchain,
        "target": toolchain["target"],
        "environment": {
            name: environment.get(name)
            for name in (
                "CARGO_HOME",
                "CARGO_TARGET_DIR",
                "RUSTC",
                "RUSTDOC",
                "RUSTUP_TOOLCHAIN",
                "RUSTFLAGS",
                "CARGO_ENCODED_RUSTFLAGS",
                "RUSTC_WRAPPER",
            )
        },
        "package_versions": json.loads(build_packages),
        "features": ["extension-module"],
        "default_features": True,
        "profile_overrides": {},
    }


def _install_environment(
    output: Path,
    python: Path,
    root: Path,
    environment: dict[str, str],
    harness: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    logs = output / "logs"
    snapshot = output / "harness-source"
    snapshot.mkdir()
    for name in harness["files_sha256"]:
        source = root / name
        if not source.is_file():
            continue
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if _sha256(destination) != harness["files_sha256"][name]:
            msg = f"Harness changed during snapshot: {name}"
            raise ValueError(msg)
    build_python = output / "build-env" / "bin" / "python"
    _run(
        [
            "uv",
            "build",
            "--wheel",
            "--python",
            str(build_python),
            "--no-build-isolation",
            "--out-dir",
            str(output / "wheels"),
            str(snapshot),
        ],
        directory=output,
        environment=environment,
        logs=logs,
        name="harness-build",
    )
    requirements = output / "dependencies.txt"
    _run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-default-groups",
            "--no-emit-project",
            "--no-emit-package",
            "foghttp",
            "--output-file",
            str(requirements),
        ],
        directory=snapshot,
        environment=environment,
        logs=logs,
        name="dependency-export",
    )
    runtime = output / "venv"
    runtime_python = runtime / "bin" / "python"
    _run(
        ["uv", "venv", "--python", str(python), str(runtime)],
        directory=output,
        environment=environment,
        logs=logs,
        name="runtime-venv",
    )
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(runtime_python),
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--requirements",
            str(requirements),
        ],
        directory=output,
        environment=environment,
        logs=logs,
        name="runtime-dependencies",
    )
    foghttp_wheel = _single_wheel(output / "wheels", "foghttp")
    harness_wheel = _single_wheel(output / "wheels", "foghttp_benchmark")
    _run(
        ["uv", "pip", "install", "--python", str(runtime_python), "--no-deps", str(foghttp_wheel), str(harness_wheel)],
        directory=output,
        environment=environment,
        logs=logs,
        name="runtime-wheels",
    )
    _run(
        ["uv", "pip", "check", "--python", str(runtime_python)],
        directory=output,
        environment=environment,
        logs=logs,
        name="runtime-check",
    )
    script = (
        "import importlib.metadata,json,platform,sys; "
        "print(json.dumps({'python_version':platform.python_version(),"
        "'package_versions':{d.metadata['Name'].lower().replace('_','-'):d.version "
        "for d in importlib.metadata.distributions()},"
        "'prefix':sys.prefix,'python_executable':sys.executable},sort_keys=True))"
    )
    installed: dict[str, Any] = json.loads(
        _run(
            [str(runtime_python), "-I", "-c", script],
            directory=output,
            environment=environment,
            logs=logs,
            name="runtime-inventory",
        ),
    )
    installed.update({"dependencies_file": str(requirements), "dependencies_sha256": _sha256(requirements)})
    return installed, inspect_distribution_wheel(harness_wheel, "foghttp-benchmark")


def _check_output_location(output: Path, root: Path) -> None:
    try:
        repository_root = Path(git_text(root, "rev-parse", "--show-toplevel")).resolve()
    except ValueError as exc:
        msg = "Research preparation requires the benchmark Git repository root"
        raise ValueError(msg) from exc
    if repository_root != root:
        msg = "Research preparation requires the benchmark Git repository root, not a nested directory"
        raise ValueError(msg)
    if not output.is_relative_to(root):
        return
    try:
        git_bytes(root, "check-ignore", "--no-index", "--quiet", "--", str(output) + os.sep)
    except ValueError as exc:
        msg = "Research output inside the benchmark checkout must be Git-ignored; select results/ or an external path"
        raise ValueError(msg) from exc


def prepare_research_environment(output: Path, python: Path, root: Path) -> Path:
    output = output.resolve()
    root = root.resolve()
    python = python.absolute()
    environment = _build_environment()
    target = _host_build_target()
    if output.exists():
        msg = f"Research output already exists: {output}"
        raise FileExistsError(msg)
    _check_output_location(output, root)
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    toolchain = _toolchain(output, environment, target)
    source = _source_checkout(output, environment)
    build = _build_foghttp(output, python, environment, source, toolchain)
    harness = capture_harness(root)
    installed, harness_wheel = _install_environment(output, python, root, environment, harness)
    _check_branch_tip(
        _run(
            ["git", "ls-remote", FOGHTTP_BASELINE.repository, FOGHTTP_BASELINE.ref],
            directory=output,
            environment=environment,
            logs=output / "logs",
            name="remote-after",
        ),
    )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": source,
        "build": build,
        "wheel": inspect_wheel(_single_wheel(output / "wheels", "foghttp")),
        "environment": installed,
        "harness": harness,
        "harness_wheel": harness_wheel,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _run(
        [installed["python_executable"], "-I", "-m", "foghttp_benchmark.research", "verify", "--manifest", str(path)],
        directory=output,
        environment=environment,
        logs=output / "logs",
        name="isolated-verify",
    )
    _run(
        [installed["python_executable"], "-I", "-m", "foghttp_benchmark.research", "smoke", "--manifest", str(path)],
        directory=output,
        environment=environment,
        logs=output / "logs",
        name="isolated-smoke",
    )
    _write_checksum_inventory(output)
    return path
