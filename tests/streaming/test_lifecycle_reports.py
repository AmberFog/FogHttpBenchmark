from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.streaming.lifecycle_aggregation import aggregate_lifecycle_results
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_reports import write_lifecycle_reports


CLIENT_RSS_BYTES = 100
SERVER_RSS_BYTES = 900
LIFETIME_RSS_BYTES = 1000
PHASE_RSS_BYTES = 90
RECOVERY_MS = 3.5
REPEAT_P95_MEDIAN_MS = 52.5


def result(*, repeat: int = 1, duration: float = 1.0) -> JsonObject:
    case = LifecycleCase(repeat, "foghttp", "async", "first-chunk-close-1m", 1, repeat)
    return {
        "case": asdict(case),
        "parent_pid": 100,
        "client_pid": 200 + repeat,
        "server_pid": 300 + repeat,
        "returncode": 0,
        "server_returncode": 0,
        "report_path": f"case-{repeat}/client.json",
        "failure": None,
        "failures": [],
        "client_report": {
            "case": asdict(case),
            "worker_pid": 200 + repeat,
            "status": "ok",
            "config": {"body_bytes": 1_048_576},
            "metadata": {},
            "errors": [],
            "client_construction_ms": 1.5,
            "client_close_ms": 2.5,
            "phases": [{"phase": "before_client_close", "lifetime_high_water_rss_bytes": 1000}],
            "batches": [
                {
                    "requests": 2,
                    "ok_streams": 2,
                    "duration_s": duration,
                    "bytes_read_total": 100,
                    "samples": [
                        {"duration_ms": 1.0, "first_item_ms": 0.5, "close_return_ms": 0.25, "first_chunk_bytes": 50},
                    ],
                },
            ],
            "warmup": {"errors": []},
            "controls": {
                "held_tail": {"status": "ok", "expected_aborts": 1},
                "recovery": {"status": "ok", "latencies_ms": [3.5]},
                "body_wait_cancel": {"status": "ok"},
                "slow_consumer_cancel": {"status": "ok"},
            },
        },
        "resources": {
            "sample_interval_s": 0.05,
            "samples": [
                {
                    "role": "client",
                    "pid": 200 + repeat,
                    "monotonic_ns": 123,
                    "rss_bytes": 100,
                    "fds": None,
                    "unavailable": {"fds": "unsupported"},
                },
                {"role": "server", "pid": 300 + repeat, "monotonic_ns": 124, "rss_bytes": 900},
            ],
            "sampled_peaks": {
                "client": {"rss_bytes": 100, "threads": 2, "fds": None},
                "server": {"rss_bytes": 900, "threads": 1, "fds": 4},
            },
            "phases": [
                {
                    "phase": "warmup",
                    "client": {"rss_bytes": 90, "threads": 2, "fds": None},
                    "server": {"rss_bytes": 800, "threads": 1, "fds": 3},
                },
            ],
            "cpu_phase_deltas": [
                {
                    "role": "client",
                    "pid": 200 + repeat,
                    "from_phase": "before_load",
                    "to_phase": "warmup",
                    "user_s": 0.1,
                    "system_s": None,
                    "unavailable": {"system_s": "unsupported"},
                },
            ],
            "truncated": False,
        },
        "stderr_tail": "retained diagnostic",
    }


def args(directory: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite="response-streaming",
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=20,
        warmup=2,
        repeats=3,
        max_redirects=5,
        seed=42,
        no_shuffle=False,
        output_dir=str(directory),
        scenarios="first-chunk-close-1m",
        iterations=5,
        client_counts="1",
    )


def write_results(directory: Path, values: list[JsonObject]) -> dict:
    plan = [LifecycleCase(**item["case"]) for item in values]
    write_lifecycle_reports(values, args(directory), LifecycleConfig(), plan)
    return json.loads((directory / "latest.json").read_text())


def test_aggregation_separates_pid_resources_cpu_and_lifetime_peaks() -> None:
    row = aggregate_lifecycle_results([result()])[0]
    assert row["resources"]["client"]["sampled_peak_rss_bytes_max"] == CLIENT_RSS_BYTES
    assert row["resources"]["server"]["sampled_peak_rss_bytes_max"] == SERVER_RSS_BYTES
    assert row["resources"]["client"]["lifetime_high_water_rss_bytes_max"] == LIFETIME_RSS_BYTES
    assert row["resources"]["server"]["lifetime_high_water_rss_bytes_max"] is None
    assert row["resources"]["client"]["sampled_peak_fds_max"] is None
    assert row["resources"]["client"]["unavailable"]["fds"] == ["unsupported"]
    assert row["cpu_phase_deltas"][0]["user_s_median"] == pytest.approx(0.1)
    assert row["cpu_phase_deltas"][0]["system_s_median"] is None
    assert row["cpu_phase_deltas"][0]["unavailable"]["system_s"] == ["unsupported"]
    assert row["phase_resources"][0]["rss_bytes_median"] == PHASE_RSS_BYTES
    assert "rss_mb_max" not in row


def test_variation_uses_fresh_repetitions_and_ten_percent_criterion(tmp_path: Path) -> None:
    two = aggregate_lifecycle_results([result(), result(repeat=2, duration=2.0)])[0]
    assert two["streams_s_cv_percent"] is None
    payload = write_results(tmp_path, [result(), result(repeat=2, duration=2.0), result(repeat=3, duration=3.0)])
    row = payload["aggregate"][0]
    assert row["ok_streams_s_median"] == 1.0
    assert row["recovery_p95_ms"] == RECOVERY_MS
    assert payload["metadata"]["validity"]["status"] == "warning"
    assert "lifecycle_high_variation" in {reason["code"] for reason in payload["metadata"]["validity"]["reasons"]}
    assert "10%" in (tmp_path / "latest.md").read_text()


def test_duration_percentile_median_keeps_repetition_boundaries() -> None:
    first = result()
    second = result(repeat=2)
    first["client_report"]["batches"][0]["samples"] = [{"duration_ms": 1.0}, {"duration_ms": 100.0}]
    second["client_report"]["batches"][0]["samples"] = [{"duration_ms": 5.0}, {"duration_ms": 5.0}]
    row = aggregate_lifecycle_results([first, second])[0]
    assert row["p95_ms_median"] == REPEAT_P95_MEDIAN_MS


def test_report_preserves_full_raw_series_and_missing_metrics(tmp_path: Path) -> None:
    original = result()
    before = deepcopy(original)
    payload = write_results(tmp_path, [original])
    assert payload["runs"] == [before]
    assert original == before
    assert payload["metadata"]["validity"]["status"] == "valid"
    assert payload["runs"][0]["resources"]["samples"][0]["fds"] is None
    assert payload["runs"][0]["resources"]["samples"][0]["unavailable"]["fds"] == "unsupported"
    assert "no competitive ranking" in (tmp_path / "latest.md").read_text()


@pytest.mark.parametrize(
    "fault",
    ["missing-child", "timeout", "pid-mismatch", "missing-control", "unknown-control-error", "sample-cap"],
)
def test_partial_failures_are_retained_and_block_validity(tmp_path: Path, fault: str) -> None:
    broken = result()
    if fault == "missing-child":
        broken["client_report"] = None
        broken["report_path"] = None
    elif fault == "timeout":
        broken["failure"] = "case deadline exceeded"
        broken["failures"] = ["case deadline exceeded"]
    elif fault == "pid-mismatch":
        broken["resources"]["samples"][0]["pid"] = 999
    elif fault == "missing-control":
        del broken["client_report"]["controls"]["recovery"]
    elif fault == "unknown-control-error":
        broken["client_report"]["controls"]["held_tail"] = {
            "status": "failed",
            "expected_aborts": 999,
            "error": "RuntimeError",
        }
    elif fault == "sample-cap":
        broken["resources"]["truncated"] = True
    payload = write_results(tmp_path, [broken])
    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["validity"]["can_compare"] is False
    assert payload["runs"][0]["stderr_tail"] == "retained diagnostic"
    if fault == "unknown-control-error":
        assert payload["aggregate"][0]["expected_aborts_total"] == 0


def test_failed_lifecycle_report_remains_readable_without_fabricating_throughput(tmp_path: Path) -> None:
    broken = result()
    broken["client_report"] = None
    broken["report_path"] = None
    write_results(tmp_path, [broken])

    report = load_benchmark_report(tmp_path / "latest.json")

    assert report.rows[0].primary_value is None
    assert report.validity.status == "invalid"
    assert not report.validity.can_compare


def test_missing_cases_and_pid_reuse_are_not_accepted(tmp_path: Path) -> None:
    original = result()
    duplicate = deepcopy(original)
    duplicate["case"]["repeat"] = 2
    duplicate["case"]["sequence"] = 2
    payload = write_results(tmp_path, [original, duplicate])
    codes = {reason["code"] for reason in payload["metadata"]["validity"]["reasons"]}
    assert "lifecycle_pid_reused" in codes
    write_lifecycle_reports(
        [original],
        args(tmp_path),
        LifecycleConfig(),
        [
            LifecycleCase(1, "foghttp", "async", "stream-1m", 1, 1),
            LifecycleCase(2, "foghttp", "async", "stream-1m", 1, 2),
        ],
    )
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert "lifecycle_plan_incomplete" in {reason["code"] for reason in payload["metadata"]["validity"]["reasons"]}


def test_different_lifecycle_configs_are_not_pooled_as_valid(tmp_path: Path) -> None:
    changed = result(repeat=2)
    changed["client_report"]["config"]["body_bytes"] = 42
    payload = write_results(tmp_path, [result(), changed])
    assert "lifecycle_configuration_mismatch" in {
        reason["code"] for reason in payload["metadata"]["validity"]["reasons"]
    }


def test_research_child_provenance_mismatch_is_still_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "foghttp_benchmark.validity.reports.research_provenance_from_env",
        lambda: {"manifest": "parent"},
    )
    original = result()
    original["client_report"]["metadata"]["research_provenance"] = {"manifest": "different"}
    payload = write_results(tmp_path, [original])
    assert payload["runs"][0]["client_report"]["metadata"]["research_provenance"] == {"manifest": "different"}
    assert payload["metadata"]["research_provenance"] == {"manifest": "parent"}
    assert "isolated_child_provenance_mismatch" in {
        reason["code"] for reason in payload["metadata"]["validity"]["reasons"]
    }
