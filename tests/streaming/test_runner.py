from foghttp_benchmark.streaming.models import StreamingCase, StreamingOutcome
from foghttp_benchmark.streaming.runner import outcome_matches


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
