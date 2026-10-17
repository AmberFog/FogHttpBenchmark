import hashlib

import pytest

from foghttp_benchmark.streaming.lifecycle_consume import expected_body_digest
from tests.streaming.lifecycle_support import BODY, PUBLIC_CHUNK, StreamCase


@pytest.mark.parametrize("size", [0, 1, 255, 256, 257, 65_535, 65_536, 65_537, 1_048_576])
def test_expected_digest_matches_the_complete_payload_and_partial_pattern_tail(size: int) -> None:
    body = bytes(index % 256 for index in range(size))

    assert expected_body_digest(size) == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("first_chunk", [False, True])
def test_stream_records_actual_public_chunks_and_explicit_close(*, asynchronous: bool, first_chunk: bool) -> None:
    case = StreamCase([BODY[:4096], BODY[4096:]], asynchronous=asynchronous, first_chunk=first_chunk)
    sample = case.run()
    assert case.client.closed
    assert sample.bytes_read == (4096 if first_chunk else len(BODY))
    assert sample.chunks_read == (1 if first_chunk else 2)
    assert sample.first_chunk_bytes == PUBLIC_CHUNK
    assert sample.eof is not first_chunk
    assert sample.close_return_ms >= 0
    assert sample.first_item_ms is not None
    assert sample.duration_ms >= sample.first_item_ms
    assert sample.content_length == str(len(BODY))


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("body", [BODY[:4096], b"x" * len(BODY), b""])
def test_eof_rejects_truncated_corrupt_and_empty_bodies(body: bytes, *, asynchronous: bool) -> None:
    case = StreamCase([body], asynchronous=asynchronous)
    with pytest.raises(ValueError):
        case.run()
    assert case.client.closed


@pytest.mark.parametrize("asynchronous", [False, True])
def test_early_close_rejects_corrupt_first_chunk(*, asynchronous: bool) -> None:
    case = StreamCase([b"x" * PUBLIC_CHUNK], asynchronous=asynchronous, first_chunk=True)

    with pytest.raises(ValueError, match="prefix integrity"):
        case.run()

    assert case.client.closed


@pytest.mark.parametrize("headers", [{"transfer-encoding": "chunked"}, {"content-encoding": "gzip"}])
def test_stream_rejects_incomparable_framing(headers: dict[str, str]) -> None:
    case = StreamCase([BODY])
    case.response.headers.update(headers)
    with pytest.raises(ValueError):
        case.run()
    assert case.client.closed
