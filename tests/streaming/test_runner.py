import asyncio
from dataclasses import replace
from functools import partial

import pytest

from foghttp_benchmark.streaming import runner
from foghttp_benchmark.streaming.cases import streaming_cases
from foghttp_benchmark.streaming.models import AsyncStreamingClientSpec, StreamingCase, StreamingOutcome
from foghttp_benchmark.streaming.runner import outcome_matches, run_streaming_case, run_streaming_load
from tests.streaming.ordinary_support import (
    AsyncOutcomeClient,
    LoadClock,
    SlowExitSampler,
    SyncOutcomeClient,
    run_controlled_http_stream,
)


EXPECTED_LOAD_SECONDS = 2.0
EXPECTED_LOAD_AND_SAMPLER_SECONDS = 29.0


def test_outcome_matches_full_stream_size() -> None:
    case = StreamingCase(
        name="stream-64k",
        path="/drip-bytes/65536/8192/0",
        size_bytes=65_536,
        chunk_size_bytes=8_192,
        delay_ms=0,
    )

    assert outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=65_536,
            chunks_read=8,
            first_chunk_ms=0.2,
        ),
    )
    assert not outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=8_192,
            chunks_read=1,
            first_chunk_ms=0.2,
        ),
    )


def test_outcome_matches_first_chunk_close() -> None:
    case = StreamingCase(
        name="first-chunk-close-1m",
        path="/drip-bytes/1048576/16384/1",
        size_bytes=1_048_576,
        chunk_size_bytes=16_384,
        delay_ms=1,
        consume="first-chunk",
    )

    assert outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=16_384,
            chunks_read=1,
            first_chunk_ms=0.2,
        ),
    )


def test_outcome_matches_line_stream_count() -> None:
    case = StreamingCase(
        name="lines-10k",
        path="/drip-text/lines-10k/4096/0",
        size_bytes=420_000,
        chunk_size_bytes=4_096,
        delay_ms=0,
        read="lines",
        expected_lines=10_000,
    )

    assert outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=420_000,
            chunks_read=10_000,
            first_chunk_ms=0.2,
            lines_read=10_000,
        ),
    )
    assert not outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=420_000,
            chunks_read=9_999,
            first_chunk_ms=0.2,
            lines_read=9_999,
        ),
    )


def test_outcome_matches_first_line_close() -> None:
    case = StreamingCase(
        name="first-line-close-10k",
        path="/drip-text/lines-10k/1024/1",
        size_bytes=420_000,
        chunk_size_bytes=1_024,
        delay_ms=1,
        read="lines",
        consume="first-line",
        expected_lines=10_000,
    )

    assert outcome_matches(
        case,
        StreamingOutcome(
            status_code=200,
            bytes_read=41,
            chunks_read=1,
            first_chunk_ms=0.2,
            lines_read=1,
        ),
    )


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_failed_observations_are_separate_from_verified_eof_throughput(mode: str) -> None:
    case = streaming_cases()["stream-64k"]
    good = StreamingOutcome(
        status_code=200,
        bytes_read=case.size_bytes,
        chunks_read=2,
        first_chunk_ms=0.1,
        body_sha256=case.expected_sha256,
        eof_received=True,
    )
    corrupt = replace(good, body_sha256="incorrect")
    truncated = replace(good, bytes_read=case.size_bytes - 1)
    bad_status = replace(good, status_code=503)
    outcomes = [good, corrupt, truncated, bad_status, TimeoutError()]
    client = AsyncOutcomeClient(outcomes) if mode == "async" else SyncOutcomeClient(outcomes)
    result = asyncio.run(run_streaming_load(client, case, "unused", 1, len(outcomes), collect=True))

    assert result.errors == len(outcomes) - 1
    assert result.error_types == {"check_failed": 3, "TimeoutError": 1}
    assert result.bytes_read == case.size_bytes * 4 - 1
    assert result.chunks_read == good.chunks_read * 4
    assert result.verified_eof_bytes == case.size_bytes
    assert result.verified_eof_chunks == good.chunks_read


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_expected_first_chunk_close_is_excluded_from_eof_throughput(mode: str) -> None:
    case = streaming_cases()["first-chunk-close-1m"]
    outcome = StreamingOutcome(status_code=200, bytes_read=100, chunks_read=1, first_chunk_ms=0.1)
    client = AsyncOutcomeClient([outcome]) if mode == "async" else SyncOutcomeClient([outcome])
    result = asyncio.run(run_streaming_load(client, case, "unused", 1, 1, collect=True))

    assert result.errors == 0
    assert result.bytes_read == outcome.bytes_read
    assert result.verified_eof_bytes == 0
    assert result.verified_eof_chunks == 0


def test_streaming_duration_excludes_sampler_enter_and_delayed_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = LoadClock()
    client = AsyncOutcomeClient([])
    monkeypatch.setattr(runner, "ResourceSampler", partial(SlowExitSampler, clock))
    monkeypatch.setattr(runner, "run_load_with_progress", clock.load)
    monkeypatch.setattr(runner.time, "perf_counter", clock.now)
    result = asyncio.run(
        run_streaming_case(
            spec=AsyncStreamingClientSpec("controlled", lambda _config: client),
            base_url="unused",
            case=streaming_cases()["stream-64k"],
            concurrency=1,
            requests=1,
            warmup=0,
            repeat=1,
        ),
    )

    assert result.duration_s == EXPECTED_LOAD_SECONDS
    assert clock.value == EXPECTED_LOAD_AND_SAMPLER_SECONDS
    assert client.closed


def test_controlled_server_and_public_bytes_consumer_verify_matching_payload() -> None:
    result = asyncio.run(run_controlled_http_stream())
    assert result.errors == 0
    assert result.verified_eof_bytes_total == streaming_cases()["stream-64k"].size_bytes
    assert result.verified_eof_chunks_total > 0
    assert result.mb_per_second > 0
