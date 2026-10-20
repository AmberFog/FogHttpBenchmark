from pathlib import Path

import pytest

from foghttp_benchmark.report_publication import publish_report


REPORT_NAMES = ("prepared.json", "latest.json", "prepared.md", "latest.md")


@pytest.mark.parametrize("existing_reports", [False, True])
def test_unserializable_payload_does_not_update_report_files(tmp_path: Path, *, existing_reports: bool) -> None:
    output_dir = tmp_path / "reports"
    if existing_reports:
        output_dir.mkdir()
        for name in REPORT_NAMES:
            (output_dir / name).write_text(f"original {name}")

    with pytest.raises(TypeError, match="not JSON serializable"):
        publish_report(output_dir, "prepared", {"unsupported": object()}, "new markdown")

    if existing_reports:
        assert sorted(path.name for path in output_dir.iterdir()) == sorted(REPORT_NAMES)
        for name in REPORT_NAMES:
            assert (output_dir / name).read_text() == f"original {name}"
    else:
        assert not output_dir.exists() or not list(output_dir.iterdir())


def test_mkdir_error_propagates_without_writing_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    for name in REPORT_NAMES:
        (output_dir / name).write_text(f"original {name}")
    failure = OSError("cannot prepare report directory")
    original_mkdir = Path.mkdir

    def fail_output_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path == output_dir:
            raise failure
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_output_mkdir)

    with pytest.raises(OSError, match="cannot prepare report directory") as raised:
        publish_report(output_dir, "prepared", {"value": "new"}, "new markdown")

    assert raised.value is failure
    for name in REPORT_NAMES:
        assert (output_dir / name).read_text() == f"original {name}"


@pytest.mark.parametrize("failed_name", REPORT_NAMES)
def test_write_error_propagates_and_preserves_completed_write_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_name: str,
) -> None:
    for name in REPORT_NAMES:
        (tmp_path / name).write_text(f"original {name}")
    expected_json = '{\n  "value": "new"\n}\n'
    expected_markdown = "new markdown\n"
    failure = OSError(f"cannot write {failed_name}")
    attempted: list[str] = []
    original_write_text = Path.write_text

    def fail_selected_write(path: Path, text: str, *args: object, **kwargs: object) -> int:
        attempted.append(path.name)
        if path == tmp_path / failed_name:
            raise failure
        return original_write_text(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_selected_write)

    with pytest.raises(OSError, match=f"cannot write {failed_name}") as raised:
        publish_report(tmp_path, "prepared", {"value": "new"}, expected_markdown)

    failed_position = REPORT_NAMES.index(failed_name)
    assert raised.value is failure
    assert attempted == list(REPORT_NAMES[: failed_position + 1])
    for position, name in enumerate(REPORT_NAMES):
        expected = expected_json if name.endswith(".json") else expected_markdown
        if position >= failed_position:
            expected = f"original {name}"
        assert (tmp_path / name).read_text() == expected
