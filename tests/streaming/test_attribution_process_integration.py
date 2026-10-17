import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.isolation.lifecycle import run_lifecycle_case
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.attribution_reports import write_attribution_reports
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from tests.streaming.lifecycle_profile_factory import lifecycle_args


DISTINCT_ROLES = 3


@pytest.mark.parametrize("client", ["foghttp", "httpx"])
@pytest.mark.parametrize("concurrency", [1, 10])
def test_isolated_async_bytes_correctness_and_resource_evidence(
    tmp_path: Path,
    client: str,
    concurrency: int,
) -> None:
    case = LifecycleCase(1, client, "async", "stream-1m", concurrency, 1)
    config = LifecycleConfig(
        body_bytes=16_384,
        server_write_bytes=1024,
        warmup_rounds=0,
        batches=1,
        rounds_per_batch=1,
        case_timeout_s=10,
        attribution=AttributionConfig(chunk_sample_cap=8),
    )

    receipt = asyncio.run(asyncio.wait_for(run_lifecycle_case(case, config, tmp_path / "case"), 15))

    assert receipt["status"] == "ok", receipt
    assert len({receipt["client_pid"], receipt["server_pid"], receipt["parent_pid"]}) == DISTINCT_ROLES
    worker = receipt["client_report"]
    batch = worker["batches"][0]
    assert batch["verified_success_bytes"] == config.body_bytes * concurrency
    assert batch["total_observed_bytes"] == batch["verified_success_bytes"]
    assert batch["failed_observed_bytes"] == 0
    assert batch["errors"] == []
    assert batch["server_health"]["status"] == "ok"
    for role in ("client", "server"):
        assert batch["cpu"][role]["pid"] == receipt[f"{role}_pid"]
        assert batch["cpu"][role]["unavailable_reason"] is None
    assert batch["overhead"]["status"] == "ok"
    assert worker["controls"]["held_tail"]["contexts_closed_before_release"] is True
    assert worker["controls"]["body_wait_cancel"]["status"] == "ok"
    assert worker["controls"]["slow_consumer_cancel"]["status"] == "ok"
    assert all(sample["content_encoding"] is None and sample["eof"] for sample in batch["samples"])
    assert all(sample["delivery_sample_count"] <= config.attribution.chunk_sample_cap for sample in batch["samples"])

    args = replace(
        lifecycle_args(tmp_path / "report"),
        streaming_profile="async-bytes",
        clients=client,
        concurrency=str(concurrency),
        streaming_payload_bytes=config.body_bytes,
        streaming_server_write_bytes=config.server_write_bytes,
        streaming_chunk_sample_cap=8,
    )
    write_attribution_reports([receipt], args, config, [case])
    report_path = tmp_path / "report/latest.json"
    report = json.loads(report_path.read_text())
    assert report["metadata"]["profile"] == "async-bytes"
    assert report["metadata"]["raw_evidence_validation"]["status"] == "ok"
    assert report["metadata"]["validity"]["can_compare"] is False  # A single tiny fixture is not research evidence.
    assert report["metadata"]["validity"]["status"] == "needs-rerun", report["metadata"]["validity"]
    assert report["aggregate"][0]["verified_bytes_total"] == config.body_bytes * concurrency
    assert report["aggregate"][0]["server_health_complete"] is True
    loaded = load_benchmark_report(report_path)
    assert loaded.validity.can_compare is False
    assert (tmp_path / "report/latest.md").is_file()


def test_explicit_httpx_reads_slow_consumer_and_diagnostic_trace_are_independent(tmp_path: Path) -> None:
    case = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
    attribution = AttributionConfig(
        requested_client_read_bytes=512,
        consumer_delay_s=0.001,
        server_delay_s=0.001,
        instrumentation="diagnostic",
        chunk_sample_cap=8,
    )
    config = LifecycleConfig(
        body_bytes=16_384,
        server_write_bytes=1024,
        warmup_rounds=0,
        batches=1,
        rounds_per_batch=1,
        case_timeout_s=10,
        attribution=attribution,
    )

    receipt = asyncio.run(asyncio.wait_for(run_lifecycle_case(case, config, tmp_path / "case"), 15))

    assert receipt["status"] == "ok", receipt
    batch = receipt["client_report"]["batches"][0]
    sample = batch["samples"][0]
    assert sample["verified_success_bytes"] == config.body_bytes
    assert sample["chunks_read"] == config.body_bytes // attribution.requested_client_read_bytes
    assert sample["distribution"]["min_bytes"] == attribution.requested_client_read_bytes
    assert sample["distribution"]["max_bytes"] == attribution.requested_client_read_bytes
    assert len(sample["trace"]) == attribution.chunk_sample_cap
    assert sample["delivery_samples_truncated"] is True
    assert batch["server_health"]["after"]["server_write_bytes"] == config.server_write_bytes
    assert batch["server_health"]["after"]["server_delay_s"] == attribution.server_delay_s
