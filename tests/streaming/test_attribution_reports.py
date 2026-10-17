import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.streaming.attribution_reports import aggregate_attribution_results, measurement_conditions
from tests.streaming.attribution_report_factory import BODY_BYTES, config, result, write_report


def test_complete_repeated_results_preserve_verified_bytes_cpu_and_raw_sidecars(tmp_path: Path) -> None:
    path = write_report(tmp_path, with_provenance=True)
    report = load_benchmark_report(path)
    row = report.aggregate_rows[0]
    assert report.validity.can_compare is True
    assert row["verified_bytes_total"] == BODY_BYTES * 3
    assert row["verified_bytes_s_median"] == BODY_BYTES
    assert row["cpu"]["client"]["user_s_median"] == pytest.approx(0.1)
    assert row["cpu"]["server"]["user_s_median"] == pytest.approx(0.3)
    payload = json.loads(path.read_text())
    assert "samples" not in payload["runs"][0]["client_report"]["batches"][0]
    reference = payload["metadata"]["raw_evidence"][0]
    raw = json.loads((tmp_path / reference["path"]).read_text())
    assert raw["result"]["client_report"]["batches"][0]["samples"][0]["sha256"]
    assert "SHA-256" in path.with_suffix(".md").read_text()


@pytest.mark.parametrize("fault", ["corruption", "missing", "escape", "aggregate-tamper", "cached-pass"])
def test_raw_evidence_is_revalidated_and_cached_pass_never_hides_damage(tmp_path: Path, fault: str) -> None:
    path = write_report(tmp_path, with_provenance=True)
    payload = json.loads(path.read_text())
    reference = payload["metadata"]["raw_evidence"][0]
    raw_path = tmp_path / reference["path"]
    if fault == "corruption":
        raw_path.write_text("{}")
    elif fault == "missing":
        raw_path.unlink()
    elif fault == "escape":
        reference["path"] = "../outside.json"
    elif fault == "aggregate-tamper":
        payload["aggregate"][0]["verified_bytes_s_median"] *= 2
    else:
        raw_path.unlink()
        payload["metadata"]["raw_evidence_validation"] = {"status": "ok", "checked": 3, "aggregates_match": True}
    path.write_text(json.dumps(payload))
    report = load_benchmark_report(path)
    assert report.validity.can_compare is False
    assert "attribution_raw_evidence_invalid" in {item.code for item in report.validity.reasons}


def test_short_correctness_run_has_no_strong_performance_validity_without_provenance(tmp_path: Path) -> None:
    report = load_benchmark_report(write_report(tmp_path, [result(1)]))
    assert report.validity.status == "needs-rerun"
    assert report.validity.can_compare is False
    assert {"attribution_provenance_missing", "attribution_repetitions_insufficient"} <= {
        item.code for item in report.validity.reasons
    }


@pytest.mark.parametrize("fault", ["server-health", "cpu-pid", "digest", "histogram"])
def test_missing_or_inconsistent_measurement_evidence_blocks_conclusions(tmp_path: Path, fault: str) -> None:
    values = [result(repeat) for repeat in range(1, 4)]
    batch = values[0]["client_report"]["batches"][0]
    if fault == "server-health":
        batch.pop("server_health")
    elif fault == "cpu-pid":
        batch["cpu"]["server"]["pid"] = values[0]["client_pid"]
    elif fault == "digest":
        batch["samples"][0]["sha256"] = "0" * 64
    else:
        batch["samples"][0]["distribution"]["histogram"][0]["count"] = 1
    report = load_benchmark_report(write_report(tmp_path, values, with_provenance=True))
    assert report.validity.status == "invalid"
    assert report.validity.can_compare is False


def test_missing_cpu_remains_none_and_records_unavailable_reason() -> None:
    value = result(1)
    cpu = value["client_report"]["batches"][0]["cpu"]["server"]
    cpu.update(user_s=None, system_s=None, total_s=None, unavailable_reason="AccessDenied")
    row = aggregate_attribution_results([value], measurement_conditions(config(), {}))[0]
    assert row["cpu"]["server"]["total_s_median"] is None
    assert row["cpu"]["server"]["unavailable"] == ["AccessDenied"]


@pytest.mark.parametrize("fault", ["partial-cpu", "partial-overhead", "latency-missing", "latency-order"])
def test_partial_missing_evidence_cannot_hide_behind_other_repeat_medians(tmp_path: Path, fault: str) -> None:
    values = [result(repeat) for repeat in range(1, 4)]
    batch = values[0]["client_report"]["batches"][0]
    if fault == "partial-cpu":
        batch["cpu"]["server"].update(user_s=None, system_s=None, total_s=None, unavailable_reason="AccessDenied")
    elif fault == "partial-overhead":
        batch["overhead"]["sha256_only_s"] = None
    elif fault == "latency-missing":
        batch["samples"][0]["first_item_ms"] = None
    else:
        batch["samples"][0]["first_item_ms"] = batch["samples"][0]["duration_ms"] + 1
    report = load_benchmark_report(write_report(tmp_path, values, with_provenance=True))
    assert report.validity.can_compare is False


@pytest.mark.parametrize("fault", ["missing-batch", "batch-number", "round-count", "stream-number", "warmup"])
def test_declared_workload_must_match_every_fresh_repeat(tmp_path: Path, fault: str) -> None:
    values = [result(repeat) for repeat in range(1, 4)]
    if fault == "missing-batch":
        for value in values:
            value["client_report"]["config"]["batches"] = 2
    elif fault == "batch-number":
        values[0]["client_report"]["batches"][0]["batch"] = 2
    elif fault == "round-count":
        values[0]["client_report"]["batches"][0]["rounds"] = 2
    elif fault == "stream-number":
        values[0]["client_report"]["batches"][0]["samples"][0]["stream"] = 2
    else:
        values[0]["client_report"]["warmup"]["requests"] = 1
    report = load_benchmark_report(write_report(tmp_path, values, with_provenance=True))
    assert report.validity.status == "invalid"
    assert report.validity.can_compare is False
