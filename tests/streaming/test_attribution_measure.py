import asyncio
from dataclasses import replace
import json

import pytest

from foghttp_benchmark.streaming import attribution_measure
from foghttp_benchmark.streaming.attribution_consume import ObservationBudget, PendingStream
from foghttp_benchmark.streaming.attribution_measure import measure_async_batch, replay_harness_overhead
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.bytes_payloads import streaming_bytes_payload
from tests.streaming.attribution_support import BODY, AttributionClient, AttributionResponse, collect, measured


def test_load_timer_excludes_cpu_end_probe_digest_finalization_and_overhead(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0]
    counter = [0]
    finalization_delay_ns = 1_000_000
    response = AttributionResponse([BODY])
    client = AttributionClient(response)
    pending = collect(client)
    finalize = PendingStream.finalize

    def cpu(pid: int) -> dict[str, object]:
        started = clock[0]
        clock[0] += 25
        counter[0] += 1
        return {
            "pid": pid,
            "probe_started_ns": started,
            "probe_finished_ns": clock[0],
            "user_s": counter[0] / 100,
            "system_s": counter[0] / 200,
            "reason": None,
        }

    async def consume(*_args: object, **_kwargs: object) -> PendingStream:
        clock[0] += 17
        return pending

    def finish(self: PendingStream, **kwargs: object) -> dict[str, object]:
        clock[0] += finalization_delay_ns
        return finalize(self, **kwargs)

    def replay(*_args: object) -> dict[str, object]:
        clock[0] += finalization_delay_ns
        return {"status": "ok"}

    monkeypatch.setattr(attribution_measure.time, "perf_counter_ns", lambda: clock[0])
    monkeypatch.setattr(attribution_measure, "_cpu_snapshot", cpu)
    monkeypatch.setattr(attribution_measure, "consume_attribution_stream", consume)
    monkeypatch.setattr(attribution_measure, "replay_harness_overhead", replay)
    monkeypatch.setattr(PendingStream, "finalize", finish)

    result = measured(client)

    assert result["duration_s"] == 17 / 1_000_000_000
    assert result["timing"]["digest_finalize_duration_ns"] == finalization_delay_ns
    assert result["cpu"]["client"]["pid"] != result["cpu"]["server"]["pid"]
    assert result["cpu"]["client"]["load_boundary_overhang_ns"] > 0
    assert result["cpu"]["client"]["total_s"] is not None
    assert result["verified_success_bytes"] == len(BODY)


def test_missing_cpu_is_null_with_reason_and_does_not_fabricate_normalization() -> None:
    result = measured(AttributionClient(AttributionResponse([BODY])))
    server = result["cpu"]["server"]

    assert server["user_s"] is None
    assert server["system_s"] is None
    assert server["cpu_seconds_per_verified_byte"] is None
    assert server["unavailable_reason"]


def test_bounded_replay_uses_exact_observed_distribution_and_retains_verification() -> None:
    client = AttributionClient(AttributionResponse([BODY[:7], BODY[7:]]))
    result = measured(client)

    assert result["verified_success_bytes"] == len(BODY)
    assert result["overhead"]["status"] == "ok"
    assert result["overhead"]["replay_bytes"] == len(BODY)
    assert result["overhead"]["replay_chunks"] == result["chunks_read_total"]
    assert result["overhead"]["sha256_only_s"] is not None
    assert result["overhead"]["scalar_only_s"] is not None
    assert result["overhead"]["combined_s"] is not None


@pytest.mark.parametrize(
    "config",
    [
        replace(AttributionConfig(), replay_max_bytes=1),
        replace(AttributionConfig(), replay_max_chunks=1),
        replace(AttributionConfig(), histogram_bins_cap=1),
    ],
)
def test_replay_refuses_partial_distribution_instead_of_presenting_an_estimate(config: AttributionConfig) -> None:
    result = measured(AttributionClient(AttributionResponse([BODY[:7], BODY[7:]])), config)

    assert result["verified_success_bytes"] == len(BODY)
    assert result["overhead"]["status"] == "unavailable"
    assert result["overhead"]["reason"]
    assert result["overhead"]["combined_s"] is None


def test_shared_budget_bounds_cross_stream_records_and_preserves_dropped_counts() -> None:
    config = replace(AttributionConfig(), instrumentation="diagnostic")
    client = AttributionClient(AttributionResponse([BODY[index : index + 1] for index in range(len(BODY))]))
    result = asyncio.run(
        measure_async_batch(
            client,
            "http://127.0.0.1",
            body_bytes=len(BODY),
            concurrency=10,
            rounds=20,
            config=config,
            server_pid=999_999_999,
            batch=1,
        ),
    )
    samples = result["samples"]
    budget = result["observation_budget"]
    records = sum(len(sample["delivery_samples"]) + len(sample["trace"]) for sample in samples)
    recorded_deliveries = sum(len(sample["delivery_samples"]) for sample in samples)

    assert records == budget["record_cap"]
    assert result["verified_success_bytes"] == len(BODY) * result["requests"]
    assert (
        sum(sample["delivery_samples_dropped"] for sample in samples)
        == result["chunks_read_total"] - recorded_deliveries
    )
    assert result["overhead"]["status"] == "ok"
    assert len(json.dumps(result)) < 2 * 1024 * 1024


def test_shared_histogram_budget_cannot_silently_turn_incomplete_replay_into_success() -> None:
    budget = ObservationBudget(record_cap=2, histogram_bins_cap=1)
    client = AttributionClient(AttributionResponse([BODY[:7], BODY[7:]]))
    sample = collect(client, budget=budget)
    replay = replay_harness_overhead([sample.observations], AttributionConfig())

    assert sample.observations.bytes_read == len(BODY)
    assert sample.observations.histogram_complete is False
    assert budget.histogram_bins == budget.histogram_bins_cap
    assert replay["status"] == "unavailable"


def test_maximum_batch_records_and_histograms_fit_the_existing_child_receipt_cap() -> None:
    config = replace(AttributionConfig(), instrumentation="diagnostic")
    sizes = range(1, config.chunk_sample_cap + 1)
    body = streaming_bytes_payload(sum(sizes))
    chunks = []
    offset = 0
    for size in sizes:
        chunks.append(body[offset : offset + size])
        offset += size
    response = AttributionResponse(chunks, headers={"content-length": str(len(body))})
    batch = asyncio.run(
        measure_async_batch(
            AttributionClient(response),
            "http://127.0.0.1",
            body_bytes=len(body),
            concurrency=10,
            rounds=20,
            config=config,
            server_pid=999_999_999,
            batch=1,
        ),
    )
    conservative_receipt = {"warmup": batch, "batches": [batch] * 5}

    assert batch["observation_budget"]["records"] == batch["observation_budget"]["record_cap"]
    assert batch["observation_budget"]["histogram_bins"] == batch["observation_budget"]["histogram_bins_cap"]
    assert len(json.dumps(conservative_receipt, indent=2).encode()) < 16 * 1024 * 1024


def test_cancellation_is_propagated_after_context_close() -> None:
    client = AttributionClient(AttributionResponse([BODY[:7]], error_after_chunks=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        collect(client)

    assert client.closed_contexts == 1
