from pathlib import Path

from foghttp_benchmark.isolation.process import clear_stale_latest_files, tail_file_text


def test_clear_stale_latest_files_preserves_timestamped_reports(tmp_path: Path) -> None:
    stale_latest_json = tmp_path / "latest.json"
    stale_latest_md = tmp_path / "latest.md"
    stale_stdout = tmp_path / "stdout.log"
    stale_stderr = tmp_path / "stderr.log"
    timestamped_report = tmp_path / "20260607-000000.json"
    stale_latest_json.write_text("{}")
    stale_latest_md.write_text("# old")
    stale_stdout.write_text("old stdout")
    stale_stderr.write_text("old stderr")
    timestamped_report.write_text("{}")

    clear_stale_latest_files(tmp_path)

    assert not stale_latest_json.exists()
    assert not stale_latest_md.exists()
    assert not stale_stdout.exists()
    assert not stale_stderr.exists()
    assert timestamped_report.exists()


def test_tail_file_text_returns_bounded_recent_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "stdout.log"
    log_path.write_text("\n".join(f"line-{line_index:03d}" for line_index in range(60)))

    value = tail_file_text(log_path)

    assert "line-000" not in value
    assert "line-020" in value
    assert value.endswith("line-059")
