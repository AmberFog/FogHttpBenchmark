from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from tests.streaming.attribution_report_factory import BODY_BYTES, result, write_report
from tests.streaming.window_report_factory import window_config, window_result, write_window_report


def test_duration_window_accepts_actual_complete_stream_count_beyond_legacy_round_limit(tmp_path: Path) -> None:
    report = load_benchmark_report(write_window_report(tmp_path))
    row = report.aggregate_rows[0]
    expected_streams = 30 * 3

    assert report.validity.status == "valid"
    assert report.validity.can_compare is True
    assert row["declared_workload_complete"] is True
    assert row["duration_window_complete"] is True
    assert row["stream_measurement_evidence_complete"] is True
    assert (
        row["expected_streams_total"]
        == row["complete_streams_total"]
        == row["stream_samples_total"]
        == expected_streams
    )
    assert row["verified_bytes_total"] == BODY_BYTES * expected_streams
    assert row["verified_bytes_s_median"] == BODY_BYTES * 30
    assert row["load_duration_s_min"] == row["load_duration_s_max"] == 1.0


def test_stream_cap_retains_complete_eof_but_blocks_short_duration_conclusions(tmp_path: Path) -> None:
    configuration = window_config(stream_limit=20)
    values = [window_result(repeat, configuration, streams=20, duration=0.25) for repeat in range(1, 4)]
    report = load_benchmark_report(write_window_report(tmp_path, values, configuration))
    row = report.aggregate_rows[0]
    expected_streams = 20 * 3

    assert report.validity.status == "needs-rerun"
    assert report.validity.can_compare is False
    assert "attribution_duration_short" in {item.code for item in report.validity.reasons}
    assert row["declared_workload_complete"] is row["stream_measurement_evidence_complete"] is True
    assert row["duration_window_complete"] is False
    assert row["expected_streams_total"] == row["complete_streams_total"] == expected_streams
    assert row["verified_bytes_total"] == BODY_BYTES * expected_streams


@pytest.mark.parametrize(
    "fault",
    [
        "global-histogram",
        "segment-histogram",
        "segment-duration",
        "actual-rounds",
        "minimum-rounds",
        "duration-flag",
        "late-digest",
        "compensating-chunk-counts",
    ],
)
def test_inconsistent_window_evidence_is_invalid_even_when_other_repeats_are_complete(
    tmp_path: Path,
    fault: str,
) -> None:
    configuration = window_config()
    values = [window_result(repeat, configuration) for repeat in range(1, 4)]
    batch = values[-1]["client_report"]["batches"][0]
    if fault == "compensating-chunk-counts":
        batch["samples"][0]["chunks_read"] = 0
        batch["samples"][0]["distribution"]["observed_count"] = 0
        batch["samples"][1]["chunks_read"] *= 2
        batch["samples"][1]["distribution"]["observed_count"] *= 2
    elif fault == "global-histogram":
        batch["window"]["global_histogram"]["histogram"][0]["count"] -= 1
    elif fault == "segment-histogram":
        batch["overhead"]["segments"][-1]["histogram"][0]["count"] -= 1
    elif fault == "segment-duration":
        batch["overhead"]["segments"][-1]["combined_s"] *= 2
    elif fault == "actual-rounds":
        batch["rounds"] -= 1
    elif fault == "minimum-rounds":
        batch["window"]["minimum_rounds"] += 1
    elif fault == "duration-flag":
        batch["window"]["target_reached"] = False
    else:
        batch["samples"][-1]["sha256"] = "0" * 64
    report = load_benchmark_report(write_window_report(tmp_path, values, configuration))

    assert report.validity.status == "invalid"
    assert report.validity.can_compare is False


def test_fixed_round_reports_still_reject_actual_rounds_differing_from_configuration(tmp_path: Path) -> None:
    values = [result(repeat) for repeat in range(1, 4)]
    values[-1]["client_report"]["batches"][0]["rounds"] = 2
    report = load_benchmark_report(write_report(tmp_path, values, with_provenance=True))

    assert report.validity.status == "invalid"
    assert report.validity.can_compare is False
