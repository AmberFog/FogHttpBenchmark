__all__ = ("streaming_cases",)

from foghttp_benchmark.streaming.models import StreamConsumeMode, StreamingCase
from foghttp_benchmark.streaming.text_payloads import TextPayload, streaming_text_payloads


def streaming_cases() -> dict[str, StreamingCase]:
    payloads = streaming_text_payloads()
    return {
        "stream-64k": StreamingCase(
            name="stream-64k",
            path="/drip-bytes/65536/8192/0",
            size_bytes=65_536,
            chunk_size_bytes=8_192,
            delay_ms=0,
            consume="all",
            description="Consume a 64 KiB streamed response to EOF.",
        ),
        "stream-1m": StreamingCase(
            name="stream-1m",
            path="/drip-bytes/1048576/16384/0",
            size_bytes=1_048_576,
            chunk_size_bytes=16_384,
            delay_ms=0,
            consume="all",
            description="Consume a 1 MiB streamed response to EOF.",
        ),
        "drip-64k-1ms": StreamingCase(
            name="drip-64k-1ms",
            path="/drip-bytes/65536/4096/1",
            size_bytes=65_536,
            chunk_size_bytes=4_096,
            delay_ms=1,
            consume="all",
            description="Consume a 64 KiB response delivered as delayed body chunks.",
        ),
        "first-chunk-close-1m": StreamingCase(
            name="first-chunk-close-1m",
            path="/drip-bytes/1048576/16384/1",
            size_bytes=1_048_576,
            chunk_size_bytes=16_384,
            delay_ms=1,
            consume="first-chunk",
            description="Read one streamed chunk and close early to measure cleanup.",
        ),
        "text-64k": _text_case(
            name="text-64k",
            payload=payloads["text-64k"],
            chunk_size_bytes=8_192,
            delay_ms=0,
            description="Consume a 64 KiB UTF-8 text response through text chunk iteration.",
        ),
        "lines-10k": _line_case(
            name="lines-10k",
            payload=payloads["lines-10k"],
            chunk_size_bytes=4_096,
            delay_ms=0,
            description="Consume a 10k-line UTF-8 response through line iteration.",
        ),
        "drip-lines-1ms": _line_case(
            name="drip-lines-1ms",
            payload=payloads["drip-lines"],
            chunk_size_bytes=1_024,
            delay_ms=1,
            description="Consume delayed UTF-8 line chunks to measure incremental line iteration.",
        ),
        "unicode-lines": _line_case(
            name="unicode-lines",
            payload=payloads["unicode-lines"],
            chunk_size_bytes=7,
            delay_ms=0,
            description="Consume UTF-8 lines with multibyte characters split across body chunks.",
        ),
        "long-line-1m": _line_case(
            name="long-line-1m",
            payload=payloads["long-line-1m"],
            chunk_size_bytes=8_192,
            delay_ms=0,
            description="Consume one 1 MiB line to measure line-buffer growth and validation overhead.",
        ),
        "first-line-close-10k": _line_case(
            name="first-line-close-10k",
            payload=payloads["lines-10k"],
            chunk_size_bytes=1_024,
            delay_ms=1,
            consume="first-line",
            description="Read one decoded line and close early to measure text stream cleanup.",
        ),
    }


def _text_case(
    *,
    name: str,
    payload: TextPayload,
    chunk_size_bytes: int,
    delay_ms: int,
    description: str,
) -> StreamingCase:
    return StreamingCase(
        name=name,
        path=f"/drip-text/{payload.name}/{chunk_size_bytes}/{delay_ms}",
        size_bytes=payload.size_bytes,
        chunk_size_bytes=chunk_size_bytes,
        delay_ms=delay_ms,
        read="text",
        description=description,
    )


def _line_case(
    *,
    name: str,
    payload: TextPayload,
    chunk_size_bytes: int,
    delay_ms: int,
    description: str,
    consume: StreamConsumeMode = "all",
) -> StreamingCase:
    return StreamingCase(
        name=name,
        path=f"/drip-text/{payload.name}/{chunk_size_bytes}/{delay_ms}",
        size_bytes=payload.size_bytes,
        chunk_size_bytes=chunk_size_bytes,
        delay_ms=delay_ms,
        read="lines",
        consume=consume,
        expected_lines=payload.line_count,
        description=description,
    )
