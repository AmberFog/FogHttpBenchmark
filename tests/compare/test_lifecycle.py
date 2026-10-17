import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.reports import render_compare_markdown
from tests.compare.factories import write_report


LEGACY_RSS_MB = 100.0
CLIENT_RSS_MB = 10.0


def streaming_row(*, lifecycle: bool = False) -> dict:
    row = {
        "mode": "async",
        "client": "foghttp",
        "case": "stream-1m",
        "read": "bytes",
        "consume": "all",
        "concurrency": 1,
        "request_limit": 1,
        "ok_streams_s_median": 20.0,
        "rss_mb_max": 100.0,
        "threads_max": 3,
        "fds_max": 8,
    }
    if lifecycle:
        row.update(
            profile="lifecycle",
            configuration={"body_bytes": 1_048_576},
            resources={
                "client": {
                    "sampled_peak_rss_bytes_max": 10 * 1024 * 1024,
                    "sampled_peak_threads_max": 2,
                    "sampled_peak_fds_max": None,
                },
                "server": {"sampled_peak_rss_bytes_max": 200 * 1024 * 1024},
            },
        )
    return row


def report(directory: Path, name: str, *, scope: str | None = None, lifecycle: bool = False) -> Path:
    path = write_report(
        directory,
        name,
        aggregate=[streaming_row(lifecycle=lifecycle)],
        foghttp_version="0.4.2",
        suite="response-streaming",
    )
    payload = json.loads(path.read_text())
    if scope is not None:
        payload["metadata"]["measurement_scope"] = scope
    if lifecycle:
        payload["metadata"]["profile"] = "lifecycle"
    path.write_text(json.dumps(payload))
    return path


def test_old_json_is_readable_but_different_resource_scopes_are_incomparable(tmp_path: Path) -> None:
    old = load_benchmark_report(report(tmp_path, "old.json"))
    new = load_benchmark_report(report(tmp_path, "new.json", scope="separate-client-server-pids-v1"))
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=5)
    summary = comparison.resource_summary
    assert old.rows[0].rss_mb == LEGACY_RSS_MB
    assert comparison.overall.rows == 1
    assert summary.comparable is False
    assert summary.old_rss_mb_max is None
    assert summary.new_rss_mb_max is None
    assert summary.old_threads_max is None
    assert summary.new_fds_max is None
    assert "Resource metrics incomparable" in render_compare_markdown(comparison)


def test_historical_resource_scope_remains_comparable_with_itself(tmp_path: Path) -> None:
    old = load_benchmark_report(report(tmp_path, "old.json"))
    new = load_benchmark_report(report(tmp_path, "new.json"))
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=5)
    assert comparison.resource_summary.comparable is True
    assert comparison.resource_summary.old_rss_mb_max == LEGACY_RSS_MB


def test_lifecycle_loader_uses_client_sampled_bytes_and_no_competitive_rankings(tmp_path: Path) -> None:
    old = load_benchmark_report(report(tmp_path, "old.json", scope="separate-client-server-pids-v1", lifecycle=True))
    new = load_benchmark_report(report(tmp_path, "new.json", scope="separate-client-server-pids-v1", lifecycle=True))
    assert old.rows[0].rss_mb == CLIENT_RSS_MB
    assert old.rows[0].fds is None
    comparison = compare_reports(old, new, focus_client="foghttp", top_n=5)
    assert comparison.wins is None


def test_lifecycle_different_configurations_do_not_match_as_equal_work(tmp_path: Path) -> None:
    old = load_benchmark_report(report(tmp_path, "old.json", lifecycle=True))
    path = report(tmp_path, "new.json", lifecycle=True)
    payload = json.loads(path.read_text())
    payload["aggregate"][0]["configuration"]["body_bytes"] = 100
    path.write_text(json.dumps(payload))
    new = load_benchmark_report(path)
    with pytest.raises(ValueError, match="No comparable rows"):
        compare_reports(old, new, focus_client="foghttp", top_n=5)
