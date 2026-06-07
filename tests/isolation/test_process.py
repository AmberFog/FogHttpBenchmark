from pathlib import Path

from foghttp_benchmark.isolation.process import clear_stale_latest_files


def test_clear_stale_latest_files_preserves_timestamped_reports(tmp_path: Path) -> None:
    stale_latest_json = tmp_path / "latest.json"
    stale_latest_md = tmp_path / "latest.md"
    timestamped_report = tmp_path / "20260607-000000.json"
    stale_latest_json.write_text("{}")
    stale_latest_md.write_text("# old")
    timestamped_report.write_text("{}")

    clear_stale_latest_files(tmp_path)

    assert not stale_latest_json.exists()
    assert not stale_latest_md.exists()
    assert timestamped_report.exists()
