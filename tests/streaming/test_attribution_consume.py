import asyncio
from dataclasses import replace

import pytest

from foghttp_benchmark.streaming.attribution_models import AttributionConfig, validate_attribution_config
from tests.streaming.attribution_support import BODY, AttributionClient, AttributionResponse, finalized, measured


@pytest.mark.parametrize(
    ("chunks", "status", "error"),
    [
        ([b"x" * len(BODY)], 200, None),
        ([BODY[:8]], 200, None),
        ([BODY], 503, None),
        ([BODY[:8]], 200, TimeoutError("read deadline")),
        ([BODY + b"x"], 200, None),
    ],
)
def test_failed_streams_retain_observed_bytes_without_verified_throughput(
    chunks: list[bytes],
    status: int,
    error: Exception | None,
) -> None:
    client = AttributionClient(AttributionResponse(chunks, status_code=status, error_after_chunks=error))
    result = measured(client)

    assert result["verified_success_bytes"] == 0
    assert result["verified_bytes_per_second"] == 0
    assert result["total_observed_bytes"] == sum(map(len, chunks))
    assert result["failed_observed_bytes"] == result["total_observed_bytes"]
    assert result["errors"]
    assert client.closed_contexts == 1


def test_full_integrity_and_native_public_delivery_are_preserved() -> None:
    response = AttributionResponse([BODY[:7], BODY[7:]])
    result = finalized(AttributionClient(response))

    assert result["status"] == "ok"
    assert result["verified_success_bytes"] == len(BODY)
    assert result["eof"] is True
    assert response.read_requests == [None]
    assert result["distribution"]["histogram"] == [{"size_bytes": 7, "count": 1}, {"size_bytes": 25, "count": 1}]
    assert result["trace"] == []


@pytest.mark.parametrize(
    "headers",
    [{"content-encoding": "gzip"}, {"content-encoding": "identity"}, {"transfer-encoding": "chunked"}],
)
def test_compression_and_incompatible_framing_fail_integrity(headers: dict[str, str]) -> None:
    response = AttributionResponse([BODY])
    response.headers.update(headers)

    assert finalized(AttributionClient(response))["verified_success_bytes"] == 0


def test_first_n_samples_and_histogram_bound_do_not_discard_total_counters() -> None:
    config = replace(AttributionConfig(), chunk_sample_cap=2, histogram_bins_cap=1, instrumentation="diagnostic")
    chunks = [BODY[:1], BODY[1:3], BODY[3:6], BODY[6:]]
    result = finalized(AttributionClient(AttributionResponse(chunks)), config)

    assert result["status"] == "ok"
    assert result["bytes_read"] == len(BODY)
    assert result["chunks_read"] == len(chunks)
    assert len(result["delivery_samples"]) == config.chunk_sample_cap
    assert len(result["gap_samples_ms"]) == 1
    assert len(result["trace"]) == config.chunk_sample_cap
    assert result["distribution"]["complete"] is False
    assert result["delivery_samples_truncated"] is True


def test_consumer_delay_is_explicit_and_independent_from_delivery_size(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    response = AttributionResponse([BODY[:7], BODY[7:]])
    config = replace(AttributionConfig(), consumer_delay_s=0.01)
    result = finalized(AttributionClient(response), config)

    assert result["verified_success_bytes"] == len(BODY)
    assert delays == [0.01]
    assert response.read_requests == [None]


@pytest.mark.parametrize("client", ["foghttp", "aiohttp", "unknown"])
def test_explicit_read_size_is_never_emulated_for_native_foghttp(client: str) -> None:
    with pytest.raises(ValueError, match="only by HTTPX"):
        validate_attribution_config(replace(AttributionConfig(), requested_client_read_bytes=8), client=client)


def test_httpx_read_request_is_passed_to_public_iterator_without_harness_rechunking() -> None:
    config = replace(AttributionConfig(), requested_client_read_bytes=8)
    validate_attribution_config(config, client="httpx")
    response = AttributionResponse([BODY])
    result = finalized(AttributionClient(response), config)

    assert response.read_requests == [8]
    assert result["chunks_read"] == 1
    assert result["distribution"]["max_bytes"] == len(BODY)


@pytest.mark.parametrize("delay", [float("nan"), float("inf"), -1, True, 2])
def test_invalid_delay_cannot_reach_the_server_or_consumer(delay: float) -> None:
    with pytest.raises(ValueError):
        validate_attribution_config(replace(AttributionConfig(), server_delay_s=delay))


def test_profiler_label_requires_diagnostic_mode() -> None:
    with pytest.raises(ValueError, match="diagnostic"):
        validate_attribution_config(replace(AttributionConfig(), profiler_label="external-profiler"))
