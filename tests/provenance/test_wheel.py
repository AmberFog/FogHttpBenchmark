import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from foghttp_benchmark import research_wheel
from tests.provenance.helpers import install_wheel, make_wheel


def test_wheel_records_bind_python_and_native_payloads(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path)

    identity = research_wheel.inspect_wheel(wheel)

    assert identity["version"] == "0.4.2"
    assert identity["native_member"] == "foghttp/_foghttp.abi3.so"
    assert identity["native_sha256"] == identity["files_sha256"]["foghttp/_foghttp.abi3.so"]
    assert "foghttp/__init__.py" in identity["files_sha256"]
    assert identity["sha256"] == research_wheel.file_sha256(wheel)


@pytest.mark.parametrize("member", ["foghttp/__init__.py", "foghttp/_foghttp.abi3.so"])
def test_wheel_corruption_fails_record_verification(tmp_path: Path, member: str) -> None:
    wheel = make_wheel(tmp_path, corrupt_member=member)

    with pytest.raises(ValueError):
        research_wheel.inspect_wheel(wheel)


def test_wheel_distribution_name_must_match_requested_package(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path, name="another-package", natives=())

    with pytest.raises(ValueError):
        research_wheel.inspect_wheel(wheel)


@pytest.mark.parametrize("natives", [(), ("foghttp/_foghttp.abi3.so", "foghttp/_foghttp.cp311.so")])
def test_foghttp_wheel_requires_one_native_module(tmp_path: Path, natives: tuple[str, ...]) -> None:
    wheel = make_wheel(tmp_path, natives=natives)

    with pytest.raises(ValueError):
        research_wheel.inspect_wheel(wheel)


@pytest.mark.parametrize("member", ["../outside.py", "/outside.py", r"foghttp\outside.py"])
def test_wheel_rejects_unsafe_members_even_with_matching_record(tmp_path: Path, member: str) -> None:
    wheel = make_wheel(tmp_path, extra_files={member: b"outside"})

    with pytest.raises(ValueError):
        research_wheel.inspect_wheel(wheel)


def test_wheel_duplicate_members_are_rejected(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path)
    with ZipFile(wheel, "a") as archive, pytest.warns(UserWarning):
        archive.writestr("foghttp/__init__.py", b"duplicate")

    with pytest.raises(ValueError):
        research_wheel.inspect_wheel(wheel)


def test_installed_wheel_matches_recorded_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = make_wheel(tmp_path)
    identity = research_wheel.inspect_wheel(wheel)
    prefix = tmp_path / "venv"
    distribution = install_wheel(wheel, prefix / "site-packages")
    monkeypatch.setattr(research_wheel.metadata, "distribution", lambda _name: distribution)

    assert research_wheel.verify_installed_wheel(identity, "foghttp", prefix) is distribution


@pytest.mark.parametrize("member", ["foghttp/__init__.py", "foghttp/_foghttp.abi3.so"])
def test_installed_file_substitution_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str) -> None:
    wheel = make_wheel(tmp_path)
    identity = research_wheel.inspect_wheel(wheel)
    prefix = tmp_path / "venv"
    distribution = install_wheel(wheel, prefix / "site-packages")
    distribution.locate_file(member).write_bytes(b"old installed payload")
    monkeypatch.setattr(research_wheel.metadata, "distribution", lambda _name: distribution)

    with pytest.raises(ValueError):
        research_wheel.verify_installed_wheel(identity, "foghttp", prefix)


@pytest.mark.parametrize("origin", ["editable", "registry", "different-wheel", "missing"])
def test_installed_origin_must_be_exact_local_noneditable_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    wheel = make_wheel(tmp_path)
    identity = research_wheel.inspect_wheel(wheel)
    prefix = tmp_path / "venv"
    distribution = install_wheel(wheel, prefix / "site-packages")
    direct_url = distribution.locate_file(distribution.dist_info) / "direct_url.json"
    if origin == "editable":
        direct_url.write_text(json.dumps({"url": wheel.as_uri(), "dir_info": {"editable": True}}))
    elif origin == "registry":
        direct_url.write_text(json.dumps({"url": "https://example.invalid/foghttp.whl"}))
    elif origin == "different-wheel":
        direct_url.write_text(json.dumps({"url": (tmp_path / "old.whl").as_uri()}))
    else:
        direct_url.unlink()
    monkeypatch.setattr(research_wheel.metadata, "distribution", lambda _name: distribution)

    with pytest.raises(ValueError):
        research_wheel.verify_installed_wheel(identity, "foghttp", prefix)


def test_installed_files_must_be_inside_recorded_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = make_wheel(tmp_path)
    identity = research_wheel.inspect_wheel(wheel)
    distribution = install_wheel(wheel, tmp_path / "outside")
    monkeypatch.setattr(research_wheel.metadata, "distribution", lambda _name: distribution)

    with pytest.raises(ValueError):
        research_wheel.verify_installed_wheel(identity, "foghttp", tmp_path / "venv")


def test_replaced_archive_invalidates_previously_recorded_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = make_wheel(tmp_path)
    identity = research_wheel.inspect_wheel(wheel)
    prefix = tmp_path / "venv"
    distribution = install_wheel(wheel, prefix / "site-packages")
    make_wheel(tmp_path, extra_files={"foghttp/added.py": b"new archive payload"})
    monkeypatch.setattr(research_wheel.metadata, "distribution", lambda _name: distribution)

    with pytest.raises(ValueError):
        research_wheel.verify_installed_wheel(identity, "foghttp", prefix)
