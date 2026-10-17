import asyncio
from dataclasses import replace
from hashlib import sha256

import pytest

from foghttp_benchmark.streaming.bytes_payloads import streaming_bytes_payload
from foghttp_benchmark.streaming.cases import streaming_cases
from foghttp_benchmark.streaming.consume import consume_async_bytes, consume_sync_bytes
from foghttp_benchmark.streaming.runner import outcome_matches
from tests.streaming.ordinary_support import async_chunks


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("mutation", ["none", "corrupt", "truncate", "bad-status"])
def test_full_bytes_verify_content_and_eof_across_chunk_boundaries(mode: str, mutation: str) -> None:
    case = streaming_cases()["stream-64k"]
    body = streaming_bytes_payload(case.size_bytes)
    if mutation == "corrupt":
        body = b"!" + body[1:]
    elif mutation == "truncate":
        body = body[:-1]
    chunks = [body[:113], body[113:30_001], body[30_001:]]
    status_code = 503 if mutation == "bad-status" else 200
    if mode == "async":
        outcome = asyncio.run(
            consume_async_bytes(async_chunks(chunks), case=case, status_code=status_code, started_ns=0),
        )
    else:
        outcome = consume_sync_bytes(iter(chunks), case=case, status_code=status_code, started_ns=0)

    assert outcome.body_sha256 == sha256(body).hexdigest()
    assert outcome.bytes_read == len(body)
    assert outcome.eof_received
    assert outcome_matches(case, outcome) == (mutation == "none")
    assert not outcome_matches(case, replace(outcome, eof_received=False))


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_first_chunk_does_not_claim_full_integrity_or_eof(mode: str) -> None:
    case = streaming_cases()["first-chunk-close-1m"]
    chunks = [b"abc", b"never read"]
    if mode == "async":
        outcome = asyncio.run(consume_async_bytes(async_chunks(chunks), case=case, status_code=200, started_ns=0))
    else:
        outcome = consume_sync_bytes(iter(chunks), case=case, status_code=200, started_ns=0)

    assert outcome.bytes_read == len(chunks[0])
    assert outcome.chunks_read == 1
    assert outcome.body_sha256 is None
    assert not outcome.eof_received
    assert outcome_matches(case, outcome)
