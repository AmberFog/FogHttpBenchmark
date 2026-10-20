from collections.abc import Callable
from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.measurement_timing import report_timing_scope
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_reports import write_lifecycle_reports
from foghttp_benchmark.streaming.reports import write_streaming_reports
from tests.resource.factories import benchmark_args
from tests.streaming.attribution_report_factory import write_report as write_attribution_fixture
from tests.streaming.factories import streaming_result
from tests.streaming.test_lifecycle_reports import result as lifecycle_result
from tests.timing.report_cases import REPORT_CASES


@pytest.mark.parametrize(("suite", "scope", "writer"), REPORT_CASES)
def test_generated_report_preserves_timing_contract_after_loading(
    tmp_path: Path,
    suite: str,
    scope: str,
    writer: Callable[[BenchmarkArgs], None],
) -> None:
    writer(replace(benchmark_args(tmp_path), suite=suite))
    report_path = tmp_path / "latest.json"
    payload = json.loads(report_path.read_text())
    loaded = load_benchmark_report(report_path)

    assert payload["runs"]
    assert payload["aggregate"]
    assert payload["metadata"]["timing_scope"] == scope
    assert loaded.metadata["timing_scope"] == scope
    assert report_timing_scope(loaded.suite, loaded.metadata, loaded.aggregate_rows) == scope


def test_lifecycle_writer_keeps_distinct_round_timing_contract(tmp_path: Path) -> None:
    value = lifecycle_result()
    plan = [LifecycleCase(**value["case"])]
    args = replace(benchmark_args(tmp_path), suite="response-streaming", streaming_profile="lifecycle")
    write_lifecycle_reports([value], args, LifecycleConfig(), plan)
    loaded = load_benchmark_report(tmp_path / "latest.json")

    assert loaded.metadata["timing_scope"] == "lifecycle-round-load-v1"
    assert report_timing_scope(loaded.suite, loaded.metadata, loaded.aggregate_rows) == "lifecycle-round-load-v1"


def test_attribution_writer_preserves_existing_fingerprinted_timing_contract(tmp_path: Path) -> None:
    loaded = load_benchmark_report(write_attribution_fixture(tmp_path))

    assert loaded.metadata["timing_scope"] == "load-only-incremental-sha256-v1"
    assert loaded.metadata["conditions"]["timing_scope"] == "load-only-incremental-sha256-v1"
    assert (
        report_timing_scope(loaded.suite, loaded.metadata, loaded.aggregate_rows) == "load-only-incremental-sha256-v1"
    )


def test_streaming_writer_does_not_relabel_explicit_legacy_measurements(tmp_path: Path) -> None:
    result = replace(streaming_result(), timing_scope="legacy-sampler-v1")
    args = replace(benchmark_args(tmp_path), suite="response-streaming")
    write_streaming_reports([result], {}, args)
    payload = json.loads((tmp_path / "latest.json").read_text())

    assert payload["metadata"]["timing_scope"] == result.timing_scope
    assert payload["metadata"]["timing_scopes"] == [result.timing_scope]
    assert payload["runs"] == [asdict(result)]
    assert payload["aggregate"][0]["timing_scope"] == result.timing_scope


@pytest.mark.parametrize(
    "scopes",
    [
        ("load-only-v2", "legacy-sampler-v1"),
        ("load-only-v2", "unknown-timing-scope"),
        ("unknown-timing-scope",),
    ],
)
def test_streaming_writer_rejects_mixed_or_unknown_timing_before_publication(
    tmp_path: Path,
    scopes: tuple[str, ...],
) -> None:
    result = streaming_result()
    args = replace(benchmark_args(tmp_path), suite="response-streaming")

    with pytest.raises(ValueError, match="timing scope"):
        write_streaming_reports([replace(result, timing_scope=scope) for scope in scopes], {}, args)

    assert not (tmp_path / "latest.json").exists()
