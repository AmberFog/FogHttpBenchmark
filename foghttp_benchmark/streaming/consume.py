__all__ = (
    "consume_async_bytes",
    "consume_async_lines",
    "consume_async_text",
    "consume_sync_bytes",
    "consume_sync_lines",
    "consume_sync_text",
)

from collections.abc import AsyncIterator, Iterator
import time

from foghttp_benchmark.streaming.models import StreamingCase, StreamingOutcome


async def consume_async_bytes(
    chunks: AsyncIterator[bytes],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    bytes_read = 0
    chunks_read = 0
    first_item_ms: float | None = None
    async for chunk in chunks:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        bytes_read += len(chunk)
        chunks_read += 1
        if case.consume == "first-chunk":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_ms=first_item_ms,
    )


def consume_sync_bytes(
    chunks: Iterator[bytes],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    bytes_read = 0
    chunks_read = 0
    first_item_ms: float | None = None
    for chunk in chunks:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        bytes_read += len(chunk)
        chunks_read += 1
        if case.consume == "first-chunk":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_ms=first_item_ms,
    )


async def consume_async_text(
    chunks: AsyncIterator[str],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    bytes_read = 0
    chunks_read = 0
    text_chars_read = 0
    first_item_ms: float | None = None
    async for chunk in chunks:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        bytes_read += len(chunk.encode())
        chunks_read += 1
        text_chars_read += len(chunk)
        if case.consume == "first-chunk":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_ms=first_item_ms,
        text_chars_read=text_chars_read,
    )


def consume_sync_text(
    chunks: Iterator[str],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    bytes_read = 0
    chunks_read = 0
    text_chars_read = 0
    first_item_ms: float | None = None
    for chunk in chunks:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        bytes_read += len(chunk.encode())
        chunks_read += 1
        text_chars_read += len(chunk)
        if case.consume == "first-chunk":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_ms=first_item_ms,
        text_chars_read=text_chars_read,
    )


async def consume_async_lines(
    lines: AsyncIterator[str],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    measured_bytes = 0
    lines_read = 0
    text_chars_read = 0
    first_item_ms: float | None = None
    async for line in lines:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        measured_bytes += len(line.encode())
        lines_read += 1
        text_chars_read += len(line)
        if case.consume == "first-line":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=_line_bytes_read(case=case, measured_bytes=measured_bytes, lines_read=lines_read),
        chunks_read=lines_read,
        first_chunk_ms=first_item_ms,
        text_chars_read=text_chars_read,
        lines_read=lines_read,
    )


def consume_sync_lines(
    lines: Iterator[str],
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    measured_bytes = 0
    lines_read = 0
    text_chars_read = 0
    first_item_ms: float | None = None
    for line in lines:
        if first_item_ms is None:
            first_item_ms = _elapsed_ms(started_ns)
        measured_bytes += len(line.encode())
        lines_read += 1
        text_chars_read += len(line)
        if case.consume == "first-line":
            break
    return StreamingOutcome(
        status_code=status_code,
        bytes_read=_line_bytes_read(case=case, measured_bytes=measured_bytes, lines_read=lines_read),
        chunks_read=lines_read,
        first_chunk_ms=first_item_ms,
        text_chars_read=text_chars_read,
        lines_read=lines_read,
    )


def _line_bytes_read(*, case: StreamingCase, measured_bytes: int, lines_read: int) -> int:
    if case.consume == "all" and lines_read > 0:
        return case.size_bytes
    return measured_bytes


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000
