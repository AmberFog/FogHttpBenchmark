__all__ = (
    "capture_harness",
    "inspect_distribution_wheel",
    "inspect_wheel",
    "package_sources",
    "research_provenance_from_env",
    "verify_research_manifest",
)

import hashlib
from importlib import import_module, metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
from typing import cast
from zipfile import BadZipFile

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.research_baseline import FOGHTTP_BASELINE
from foghttp_benchmark.research_wheel import (
    file_sha256,
    inspect_distribution_wheel,
    inspect_wheel,
    verify_installed_wheel,
)


RESEARCH_MANIFEST_ENV = "FOGHTTP_BENCHMARK_RESEARCH_MANIFEST"


def git_bytes(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(  # noqa: S603 - fixed Git executable and argument vectors, without a shell.
            ["/usr/bin/git", "-C", str(repo), *args],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        msg = f"Cannot verify Git state: {repo} ({args[0]})"
        raise ValueError(msg) from exc


def git_text(repo: Path, *args: str) -> str:
    return git_bytes(repo, *args).decode().strip()


def capture_harness(root: Path) -> JsonObject:
    root = root.resolve()
    paths = git_bytes(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    hashes = {name: file_sha256(root / name) for name in paths if name and (root / name).is_file()}
    return {
        "root": str(root),
        "sha": git_text(root, "rev-parse", "HEAD"),
        "branch": git_text(root, "branch", "--show-current"),
        "dirty": bool(git_text(root, "status", "--porcelain")),
        "diff_sha256": hashlib.sha256(git_bytes(root, "diff", "--binary", "HEAD")).hexdigest(),
        "files_sha256": hashes,
    }


def object_field(value: JsonObject, field: str) -> JsonObject:
    item = value.get(field)
    if not isinstance(item, dict):
        msg = f"Missing or invalid provenance object: {field}"
        raise TypeError(msg)
    return cast("JsonObject", item)


def verify_source(source: JsonObject, *, check_remote: bool) -> None:
    expected = {
        "repository": FOGHTTP_BASELINE.repository,
        "ref": FOGHTTP_BASELINE.ref,
        "tip": FOGHTTP_BASELINE.sha,
        "sha": FOGHTTP_BASELINE.sha,
        "dirty": False,
    }
    if any(source.get(key) != value for key, value in expected.items()):
        msg = "FogHTTP baseline differs from the explicitly selected release revision"
        raise ValueError(msg)
    checkout = Path(str(source["checkout"]))
    if git_text(checkout, "rev-parse", "HEAD") != FOGHTTP_BASELINE.sha or git_text(checkout, "status", "--porcelain"):
        msg = "FogHTTP source checkout is dirty or has the wrong revision"
        raise ValueError(msg)
    if git_text(checkout, "branch", "--show-current"):
        msg = "FogHTTP build checkout must have detached HEAD"
        raise ValueError(msg)
    if git_text(checkout, "rev-parse", "HEAD^{tree}") != source.get("tree"):
        msg = "FogHTTP source tree differs from manifest"
        raise ValueError(msg)
    git_bytes(checkout, "merge-base", "--is-ancestor", FOGHTTP_BASELINE.sha, str(source["tip"]))
    for name, field in (("Cargo.lock", "cargo_lock_sha256"), ("pyproject.toml", "pyproject_sha256")):
        if file_sha256(checkout / name) != source.get(field):
            msg = f"FogHTTP source input changed: {name}"
            raise ValueError(msg)
    if check_remote:
        tip = git_text(checkout, "ls-remote", FOGHTTP_BASELINE.repository, FOGHTTP_BASELINE.ref).split()
        if not tip or tip[0] != source["tip"]:
            msg = "Release branch advanced; explicitly select and record a baseline before continuing"
            raise ValueError(msg)


def verify_build(build: JsonObject) -> None:
    command = build.get("command")
    if build.get("profile") != "release" or not isinstance(command, list):
        msg = "Missing release build evidence"
        raise ValueError(msg)
    if "--release" not in command or "--locked" not in command or "--profile" in command:
        msg = "Build must explicitly use the locked release profile"
        raise ValueError(msg)
    log = Path(str(build["log"]))
    if file_sha256(log) != build.get("log_sha256"):
        msg = "Build log checksum mismatch"
        raise ValueError(msg)
    lines = log.read_text().splitlines()
    optimized = any("--crate-name foghttp " in line and "opt-level=3" in line for line in lines)
    if not optimized or not any("release" in line and "optimized" in line and "Finished" in line for line in lines):
        msg = "Build log does not prove optimized FogHTTP release compilation"
        raise ValueError(msg)
    tools = object_field(build, "toolchain")
    for name in ("rustc", "cargo", "maturin", "uv"):
        if not tools.get(name):
            msg = f"Build tool version is missing: {name}"
            raise ValueError(msg)
    verify_build_overrides(object_field(build, "environment"))


def verify_build_overrides(environment: JsonObject) -> None:
    for name, value in environment.items():
        if name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER") and value:
            msg = f"Unqualified compiler override in build: {name}"
            raise ValueError(msg)
        if name.startswith("CARGO_PROFILE_"):
            allowed = {"CARGO_PROFILE_RELEASE_OPT_LEVEL": "3", "CARGO_PROFILE_RELEASE_DEBUG_ASSERTIONS": "false"}
            if allowed.get(name) != value:
                msg = f"Unqualified profile override: {name}"
                raise ValueError(msg)


def installed_versions() -> dict[str, str]:
    return {str(dist.metadata["Name"]).lower().replace("_", "-"): dist.version for dist in metadata.distributions()}


def verify_environment(environment: JsonObject) -> None:
    if str(Path(sys.executable).absolute()) != environment.get("python_executable"):
        msg = "Research child uses the wrong Python interpreter"
        raise ValueError(msg)
    prefix = Path(sys.prefix)
    if str(prefix.resolve()) != environment.get("prefix") or sys.prefix == sys.base_prefix:
        msg = "Research requires the recorded isolated virtual environment"
        raise ValueError(msg)
    config = (prefix / "pyvenv.cfg").read_text().lower().replace(" ", "")
    if "include-system-site-packages=false" not in config:
        msg = "Research environment must exclude system site-packages"
        raise ValueError(msg)
    if os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
        msg = "Research environment rejects PYTHONPATH/PYTHONHOME shadowing"
        raise ValueError(msg)
    if platform.python_version() != environment.get("python_version"):
        msg = "Research Python version changed"
        raise ValueError(msg)
    if installed_versions() != environment.get("package_versions"):
        msg = "Installed dependency versions differ from manifest"
        raise ValueError(msg)
    if file_sha256(Path(str(environment["dependencies_file"]))) != environment.get("dependencies_sha256"):
        msg = "Research dependency lock changed"
        raise ValueError(msg)


def installation_identity(manifest: JsonObject) -> JsonObject:
    environment = object_field(manifest, "environment")
    verify_environment(environment)
    prefix = Path(sys.prefix)
    wheel = object_field(manifest, "wheel")
    if wheel.get("version") != FOGHTTP_BASELINE.version:
        msg = f"Research requires FogHTTP {FOGHTTP_BASELINE.version}"
        raise ValueError(msg)
    distribution = verify_installed_wheel(wheel, "foghttp", prefix)
    harness_wheel = object_field(manifest, "harness_wheel")
    verify_installed_wheel(harness_wheel, "foghttp-benchmark", prefix)
    source = object_field(manifest, "source")
    checkout = Path(str(source["checkout"]))
    source_paths = git_bytes(checkout, "ls-files", "-z", "foghttp/").decode().split("\0")
    source_hashes: JsonObject = {name: file_sha256(checkout / name) for name in source_paths if name}
    verify_package_payload(source_hashes, wheel, "foghttp/")
    verify_package_payload(
        object_field(object_field(manifest, "harness"), "files_sha256"),
        harness_wheel,
        "foghttp_benchmark/",
    )
    package = import_module("foghttp")
    native = import_module("foghttp._foghttp")
    harness = import_module("foghttp_benchmark")
    for module, member, owner in (
        (package, "foghttp/__init__.py", distribution),
        (native, str(wheel["native_member"]), distribution),
        (harness, "foghttp_benchmark/__init__.py", metadata.distribution("foghttp-benchmark")),
    ):
        if Path(str(module.__file__)).resolve() != Path(str(owner.locate_file(member))).resolve():
            msg = f"Imported module shadows the installed wheel: {module.__name__}"
            raise ValueError(msg)
    return {
        "python_executable": sys.executable,
        "prefix": str(prefix.resolve()),
        "package_version": distribution.version,
        "module_file": str(Path(str(package.__file__)).resolve()),
        "native_file": str(Path(str(native.__file__)).resolve()),
        "native_sha256": file_sha256(Path(str(native.__file__))),
        "package_versions": installed_versions(),
    }


def verify_package_payload(source_hashes: JsonObject, wheel: JsonObject, package: str) -> None:
    expected = {
        name: digest
        for name, digest in source_hashes.items()
        if name.startswith(package) and name.endswith((".py", ".pyi", ".j2", "py.typed"))
    }
    actual = {
        name: digest
        for name, digest in object_field(wheel, "files_sha256").items()
        if name.startswith(package) and name.endswith((".py", ".pyi", ".j2", "py.typed"))
    }
    if not expected or actual != expected:
        msg = f"Wheel package files differ from the recorded source: {package}"
        raise ValueError(msg)


def verify_research_manifest(path: Path, *, check_remote: bool = False) -> JsonObject:
    try:
        data = path.read_bytes()
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            msg = "Missing or unsupported research manifest"
            raise ValueError(msg)
        manifest = cast("JsonObject", value)
        verify_source(object_field(manifest, "source"), check_remote=check_remote)
        verify_build(object_field(manifest, "build"))
        harness = object_field(manifest, "harness")
        if capture_harness(Path(str(harness["root"]))) != harness:
            msg = "Benchmark checkout changed since wheel preparation"
            raise ValueError(msg)
        installation = installation_identity(manifest)
    except (OSError, KeyError, TypeError, BadZipFile, metadata.PackageNotFoundError) as exc:
        msg = f"Incomplete research provenance: {exc}"
        raise ValueError(msg) from exc
    return {"manifest_sha256": hashlib.sha256(data).hexdigest(), "manifest": manifest, "installation": installation}


def research_provenance_from_env(*, check_remote: bool = False) -> JsonObject | None:
    path = os.environ.get(RESEARCH_MANIFEST_ENV)
    if path is None:
        return None
    if not path:
        msg = "Research manifest path cannot be empty"
        raise ValueError(msg)
    return verify_research_manifest(Path(path), check_remote=check_remote)


def package_sources(names: list[str]) -> dict[str, JsonObject]:
    return {name: package_source(name) for name in names}


def package_source(name: str) -> JsonObject:
    try:
        module = import_module(name)
    except ImportError:
        return {"status": "not imported"}
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        return {"status": "unknown"}
    path = Path(module_file).resolve()
    source: JsonObject = {"module_file": str(path)}
    for key in ("purelib", "platlib"):
        root = Path(sysconfig.get_path(key)).resolve()
        if path.is_relative_to(root):
            source.update(source_type="installed", site_packages_root=str(root))
            return source
    for parent in path.parents:
        if (parent / ".git").exists():
            source.update(
                source_type="local-git",
                git_root=str(parent),
                git_branch=git_text(parent, "branch", "--show-current"),
                git_sha=git_text(parent, "rev-parse", "HEAD"),
                git_dirty=bool(git_text(parent, "status", "--porcelain")),
            )
            return source
    source["source_type"] = "path"
    return source
