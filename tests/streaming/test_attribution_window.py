import asyncio
from dataclasses import replace
import hashlib
import json

import pytest

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming import attribution_measure
from foghttp_benchmark.streaming.attribution_consume import ChunkObservations, ObservationBudget, PendingStream
from foghttp_benchmark.streaming.attribution_measure import measure_async_batch, replay_harness_overhead
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from tests.streaming.attribution_support import BODY
from tests.streaming.window_support import WindowClient, WindowClock


def measured_window(
    monkeypatch: pytest.MonkeyPatch,
    clock: WindowClock,
    *,
    concurrency: int = 1,
    rounds: int = 1,
    maximum: int = 2048,
    corrupt_stream: int | None = None,
    batch: int = 1,
    diagnostic: bool = False,
    chunk_bytes: int | None = None,
) -> JsonObject:
    monkeypatch.setattr(attribution_measure.time, "perf_counter_ns", clock)
    return asyncio.run(
        measure_async_batch(
            WindowClient(clock, corrupt_stream=corrupt_stream, chunk_bytes=chunk_bytes),
            "http://127.0.0.1",
            body_bytes=len(BODY),
            concurrency=concurrency,
            rounds=rounds,
            config=AttributionConfig(
                minimum_duration_s=1.0,
                max_window_streams=maximum,
                instrumentation="diagnostic" if diagnostic else "control",
            ),
            server_pid=999_999_999,
            batch=batch,
        ),
    )


def test_window_reaches_duration_only_between_complete_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_rounds, expected_requests = 15, 150
    result = measured_window(monkeypatch, WindowClock(step_ns=7_000_000), concurrency=10)

    assert result["duration_s"] == pytest.approx(1.05)
    assert result["requests"] == expected_requests
    assert result["rounds"] == expected_rounds
    assert result["window"]["stop_reason"] == "duration-reached"
    assert result["window"]["target_reached"] is True
    assert [sample["stream"] for sample in result["samples"]] == list(range(1, 151))
    assert result["verified_success_bytes"] == 150 * len(BODY)


def test_minimum_rounds_remain_mandatory_even_after_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    minimum_rounds = 3
    result = measured_window(monkeypatch, WindowClock(step_ns=600_000_000), rounds=minimum_rounds)

    assert result["requests"] == minimum_rounds
    assert result["duration_s"] == pytest.approx(1.8)
    assert result["window"]["minimum_rounds"] == minimum_rounds


def test_stream_limit_retains_incomplete_duration_without_partial_round(monkeypatch: pytest.MonkeyPatch) -> None:
    maximum, actual_streams, actual_rounds = 25, 20, 2
    result = measured_window(monkeypatch, WindowClock(step_ns=1_000_000), concurrency=10, maximum=maximum)

    assert result["requests"] == actual_streams
    assert result["rounds"] == actual_rounds
    assert result["window"]["max_streams"] == maximum
    assert result["window"]["target_reached"] is False
    assert result["window"]["stop_reason"] == "stream-limit"
    assert result["verified_success_bytes"] == 20 * len(BODY)


def test_window_rejects_minimum_rounds_larger_than_explicit_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="minimum rounds"):
        measured_window(monkeypatch, WindowClock(), concurrency=10, rounds=3, maximum=20)


def test_warmup_keeps_fixed_rounds_and_per_stream_histograms(monkeypatch: pytest.MonkeyPatch) -> None:
    rounds = 2
    result = measured_window(monkeypatch, WindowClock(step_ns=100_000_000), rounds=rounds, batch=0)

    assert "window" not in result
    assert result["requests"] == rounds
    assert result["samples"][0]["distribution"]["histogram"] == [{"size_bytes": len(BODY), "count": 1}]
    assert "scope" not in result["samples"][0]["distribution"]


def test_digest_finalization_occurs_after_load_and_corruption_is_never_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = WindowClock(step_ns=250_000_000)
    finalization_ns, expected_streams, expected_ok = 2_000_000_000, 4, 3
    finalize = PendingStream.finalize
    finalization_started: list[int] = []

    def delayed_finalization(self: PendingStream, **kwargs: object) -> dict[str, object]:
        finalization_started.append(clock.now_ns)
        clock.now_ns += finalization_ns
        return finalize(self, **kwargs)

    monkeypatch.setattr(PendingStream, "finalize", delayed_finalization)
    result = measured_window(monkeypatch, clock, corrupt_stream=4)

    assert result["duration_s"] == 1.0
    assert finalization_started[0] == result["timing"]["load_finished_ns"]
    assert result["timing"]["digest_finalize_duration_ns"] == finalization_ns * expected_streams
    assert result["ok_streams"] == expected_ok
    assert result["verified_success_bytes"] == 3 * len(BODY)
    assert result["total_observed_bytes"] == 4 * len(BODY)
    assert result["samples"][-1]["error"]["type"] == "IntegrityError"
    assert all(sample["eof"] for sample in result["samples"])


def test_window_histogram_counts_unique_sizes_once_and_records_remain_globally_bounded() -> None:
    bins, records = 2, 5
    config = AttributionConfig(instrumentation="diagnostic", histogram_bins_cap=bins)
    budget = ObservationBudget(record_cap=records, histogram_bins_cap=bins, global_histogram={})
    observations = [ChunkObservations(config, budget) for _ in range(100)]
    for observation in observations:
        observation.observe(BODY[:7], 1, 0)
        observation.observe(BODY[7:], 2, 0)

    assert budget.global_histogram == {7: 100, 25: 100}
    assert budget.histogram_bins == bins
    assert budget.global_histogram_complete is True
    assert sum(len(item.delivery_samples) for item in observations) == records
    assert all(not item.histogram for item in observations)
    assert all(item.payload()["distribution"]["scope"] == "batch-global" for item in observations)
    observations[-1].observe(b"new", 3, 0)
    assert budget.global_histogram_complete is False
    assert all(item.payload()["distribution"]["complete"] is False for item in observations)
    assert replay_harness_overhead(observations, config, window_budget=budget)["status"] == "unavailable"


def test_segmented_replay_covers_exact_distribution_with_unchanged_per_segment_limits() -> None:
    expected_chunks = 20
    config = replace(AttributionConfig(), replay_max_bytes=64, replay_max_chunks=3)
    budget = ObservationBudget(histogram_bins_cap=2, global_histogram={})
    observations = [ChunkObservations(config, budget) for _ in range(10)]
    for observation in observations:
        observation.observe(BODY[:7], 1, 0)
        observation.observe(BODY[7:], 2, 0)
    result = replay_harness_overhead(observations, config, window_budget=budget)

    assert result["status"] == "ok"
    assert result["replay_bytes"] == 10 * len(BODY)
    assert result["replay_chunks"] == expected_chunks
    assert len(result["segments"]) > 1
    exact: dict[int, int] = {}
    for segment in result["segments"]:
        assert segment["replay_bytes"] <= config.replay_max_bytes
        assert segment["replay_chunks"] <= config.replay_max_chunks
        for entry in segment["histogram"]:
            exact[entry["size_bytes"]] = exact.get(entry["size_bytes"], 0) + entry["count"]
    assert exact == budget.global_histogram
    for key in ("scalar_only_s", "sha256_only_s", "combined_s"):
        assert result[key] == sum(segment[key] for segment in result["segments"])


def test_oversize_single_chunk_does_not_create_an_empty_replay_segment_loop() -> None:
    config = replace(AttributionConfig(), replay_max_bytes=1)
    budget = ObservationBudget(global_histogram={})
    observation = ChunkObservations(config, budget)
    observation.observe(BODY, 1, 0)

    result = replay_harness_overhead([observation], config, window_budget=budget)

    assert result["status"] == "unavailable"
    assert result["replay_bytes"] == 0
    assert "chunk exceeds" in result["reason"]


def test_replay_refuses_more_than_64_segments_instead_of_replaying_a_partial_window() -> None:
    config = replace(AttributionConfig(), replay_max_bytes=32, replay_max_chunks=1)
    budget = ObservationBudget(global_histogram={})
    observation = ChunkObservations(config, budget)
    for index in range(65):
        observation.observe(BODY, index + 1, 0)

    result = replay_harness_overhead([observation], config, window_budget=budget)

    assert result["status"] == "unavailable"
    assert result["reason"] == "Exact distribution exceeds the bounded 64-segment replay limit"
    assert result["replay_bytes"] == 0
    assert result["combined_s"] is None


def test_maximum_window_keeps_individual_integrity_evidence_within_existing_receipt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum, records = 2048, 4096
    result = measured_window(monkeypatch, WindowClock(step_ns=1), maximum=maximum, diagnostic=True, chunk_bytes=1)

    assert result["requests"] == maximum
    assert result["window"]["target_reached"] is False
    assert result["window"]["global_histogram"]["histogram"] == [{"size_bytes": 1, "count": 2048 * len(BODY)}]
    assert result["observation_budget"]["records"] == records
    assert sum(len(sample["trace"]) + len(sample["delivery_samples"]) for sample in result["samples"]) == records
    assert all(sample["sha256"] == hashlib.sha256(BODY).hexdigest() for sample in result["samples"])
    assert all(sample["eof"] for sample in result["samples"])
    assert len(json.dumps(result, indent=2).encode()) < 16 * 1024 * 1024
