from pathlib import Path
import platform
import sys
from types import ModuleType

import pytest

from foghttp_benchmark import provenance
from foghttp_benchmark.models import JsonObject
from tests.provenance.helpers import InstalledDistribution, install_wheel, make_wheel


@pytest.fixture
def isolated_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]]:
    prefix = tmp_path / "venv"
    prefix.mkdir()
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    executable = prefix / "bin" / "python"
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)
    distributions: dict[str, InstalledDistribution] = {}
    wheels: dict[str, JsonObject] = {}
    for name in ("foghttp", "foghttp-benchmark"):
        wheel_path = make_wheel(tmp_path, name=name, natives=("foghttp/_foghttp.abi3.so",) if name == "foghttp" else ())
        wheels[name] = provenance.inspect_distribution_wheel(wheel_path, name)
        distributions[name] = install_wheel(wheel_path, prefix / "site-packages")
    monkeypatch.setattr(provenance.metadata, "distribution", lambda name: distributions[name])
    monkeypatch.setattr(provenance.metadata, "distributions", lambda: list(distributions.values()))
    dependencies_file = tmp_path / "dependencies.txt"
    dependencies_file.write_text("foghttp==0.4.2\nfoghttp-benchmark==0.1.0\n")
    checkout = tmp_path / "source"
    (checkout / "foghttp").mkdir(parents=True)
    (checkout / "foghttp" / "__init__.py").write_bytes(
        distributions["foghttp"].locate_file("foghttp/__init__.py").read_bytes(),
    )
    provenance.git_bytes(checkout, "init")
    provenance.git_bytes(checkout, "add", "foghttp")
    manifest: JsonObject = {
        "wheel": wheels["foghttp"],
        "harness_wheel": wheels["foghttp-benchmark"],
        "source": {"checkout": str(checkout)},
        "harness": {"files_sha256": wheels["foghttp-benchmark"]["files_sha256"]},
        "environment": {
            "python_executable": str(executable),
            "prefix": str(prefix.resolve()),
            "python_version": platform.python_version(),
            "package_versions": {"foghttp": "0.4.2", "foghttp-benchmark": "0.1.0"},
            "dependencies_file": str(dependencies_file),
            "dependencies_sha256": provenance.file_sha256(dependencies_file),
        },
    }
    modules: dict[str, ModuleType] = {}
    for module_name, distribution_name, member in (
        ("foghttp", "foghttp", "foghttp/__init__.py"),
        ("foghttp._foghttp", "foghttp", "foghttp/_foghttp.abi3.so"),
        ("foghttp_benchmark", "foghttp-benchmark", "foghttp_benchmark/__init__.py"),
    ):
        module = ModuleType(module_name)
        module.__file__ = str(distributions[distribution_name].locate_file(member))
        modules[module_name] = module
    monkeypatch.setattr(provenance, "import_module", lambda name: modules[name])
    return manifest, distributions, modules


def test_installation_identity_binds_imports_to_both_installed_wheels(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
) -> None:
    manifest, _distributions, modules = isolated_installation

    identity = provenance.installation_identity(manifest)

    assert identity["native_file"] == modules["foghttp._foghttp"].__file__
    assert identity["native_sha256"] == manifest["wheel"]["native_sha256"]
    assert identity["module_file"] == modules["foghttp"].__file__
    assert identity["package_versions"] == manifest["environment"]["package_versions"]


def test_unknown_wheel_version_cannot_redefine_the_reviewed_baseline(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
) -> None:
    manifest, _distributions, _modules = isolated_installation
    manifest["wheel"]["version"] = "0.4.3"

    with pytest.raises(ValueError, match=r"Research requires FogHTTP 0\.4\.2"):
        provenance.installation_identity(manifest)


@pytest.mark.parametrize("module_name", ["foghttp", "foghttp._foghttp", "foghttp_benchmark"])
def test_imported_modules_cannot_shadow_verified_installed_files(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
    tmp_path: Path,
    module_name: str,
) -> None:
    manifest, _distributions, modules = isolated_installation
    shadow = tmp_path / "shadow" / "module.py"
    shadow.parent.mkdir()
    shadow.write_bytes(b"old module from another checkout")
    modules[module_name].__file__ = str(shadow)

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


@pytest.mark.parametrize("changed", ["interpreter", "prefix", "dependencies", "lock", "version", "system-site"])
def test_environment_must_match_recorded_interpreter_dependencies_and_isolation(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
    changed: str,
) -> None:
    manifest, _distributions, _modules = isolated_installation
    environment = manifest["environment"]
    if changed == "interpreter":
        environment["python_executable"] = "/another/python"
    elif changed == "prefix":
        environment["prefix"] = "/another/venv"
    elif changed == "dependencies":
        environment["package_versions"]["foghttp"] = "0.4.1"
    elif changed == "lock":
        Path(environment["dependencies_file"]).write_text("foghttp==0.4.1\n")
    elif changed == "version":
        environment["python_version"] = "3.10.0"
    else:
        (Path(sys.prefix) / "pyvenv.cfg").write_text("include-system-site-packages = true\n")

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


@pytest.mark.parametrize("name", ["PYTHONPATH", "PYTHONHOME"])
def test_shadowing_environment_variables_are_rejected(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    manifest, _distributions, _modules = isolated_installation
    monkeypatch.setenv(name, "/another/source")

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


def test_nonvirtual_environment_is_rejected(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _distributions, _modules = isolated_installation
    monkeypatch.setattr(sys, "base_prefix", sys.prefix)

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


def test_installed_harness_substitution_is_rejected(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
) -> None:
    manifest, distributions, _modules = isolated_installation
    distributions["foghttp-benchmark"].locate_file("foghttp_benchmark/__init__.py").write_bytes(b"changed benchmark")

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


@pytest.mark.parametrize("package", ["foghttp", "foghttp_benchmark"])
def test_wheel_payload_must_match_the_recorded_source(
    isolated_installation: tuple[JsonObject, dict[str, InstalledDistribution], dict[str, ModuleType]],
    package: str,
) -> None:
    manifest, _distributions, _modules = isolated_installation
    if package == "foghttp":
        source = Path(manifest["source"]["checkout"]) / "foghttp" / "__init__.py"
        source.write_bytes(b"source changed independently of the recorded wheel")
    else:
        manifest["harness"]["files_sha256"]["foghttp_benchmark/__init__.py"] = "another source digest"

    with pytest.raises(ValueError):
        provenance.installation_identity(manifest)


@pytest.mark.parametrize("content", [None, "[]", "{}", '{"schema_version": 2}', '{"schema_version": 1}'])
def test_missing_or_incomplete_manifest_is_rejected(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "manifest.json"
    if content is not None:
        path.write_text(content)

    with pytest.raises(ValueError):
        provenance.verify_research_manifest(path)


def test_empty_manifest_environment_variable_cannot_disable_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(provenance.RESEARCH_MANIFEST_ENV, "")

    with pytest.raises(ValueError):
        provenance.research_provenance_from_env()


def test_absent_manifest_environment_preserves_ordinary_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(provenance.RESEARCH_MANIFEST_ENV, raising=False)

    assert provenance.research_provenance_from_env() is None
