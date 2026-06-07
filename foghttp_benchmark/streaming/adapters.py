__all__ = (
    "AioHTTPAsyncStreamingAdapter",
    "FogHTTPAsyncStreamingAdapter",
    "FogHTTPSyncStreamingAdapter",
    "HTTPXAsyncStreamingAdapter",
    "HTTPXSyncStreamingAdapter",
)

import codecs
from collections.abc import AsyncIterator
import time

from foghttp_benchmark.clients.utils import stats_from_client
from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.streaming.consume import (
    consume_async_bytes,
    consume_async_lines,
    consume_async_text,
    consume_sync_bytes,
    consume_sync_lines,
    consume_sync_text,
)
from foghttp_benchmark.streaming.models import StreamingCase, StreamingOutcome
from foghttp_benchmark.streaming.protocols import (
    AioHTTPClient,
    AioHTTPContent,
    AsyncStatsStreamClient,
    AsyncStreamClient,
    AsyncStreamResponse,
    SyncStatsStreamClient,
    SyncStreamClient,
    SyncStreamResponse,
)


class FogHTTPAsyncStreamingAdapter:
    def __init__(self, client: AsyncStatsStreamClient) -> None:
        self.client = client

    async def stream(self, case: StreamingCase, url: str) -> StreamingOutcome:
        started_ns = time.perf_counter_ns()
        async with self.client.stream("GET", url) as response:
            return await _consume_async_response(
                response,
                case=case,
                status_code=int(response.status_code),
                started_ns=started_ns,
            )

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> ClientStats | None:
        return stats_from_client(self.client)


class FogHTTPSyncStreamingAdapter:
    def __init__(self, client: SyncStatsStreamClient) -> None:
        self.client = client

    def stream(self, case: StreamingCase, url: str) -> StreamingOutcome:
        started_ns = time.perf_counter_ns()
        with self.client.stream("GET", url) as response:
            return _consume_sync_response(
                response,
                case=case,
                status_code=int(response.status_code),
                started_ns=started_ns,
            )

    def close(self) -> None:
        self.client.close()

    def stats(self) -> ClientStats | None:
        return stats_from_client(self.client)


class HTTPXAsyncStreamingAdapter:
    def __init__(self, client: AsyncStreamClient) -> None:
        self.client = client

    async def stream(self, case: StreamingCase, url: str) -> StreamingOutcome:
        started_ns = time.perf_counter_ns()
        async with self.client.stream("GET", url) as response:
            return await _consume_async_response(
                response,
                case=case,
                status_code=int(response.status_code),
                started_ns=started_ns,
            )

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> ClientStats | None:
        return None


class HTTPXSyncStreamingAdapter:
    def __init__(self, client: SyncStreamClient) -> None:
        self.client = client

    def stream(self, case: StreamingCase, url: str) -> StreamingOutcome:
        started_ns = time.perf_counter_ns()
        with self.client.stream("GET", url) as response:
            return _consume_sync_response(
                response,
                case=case,
                status_code=int(response.status_code),
                started_ns=started_ns,
            )

    def close(self) -> None:
        self.client.close()

    def stats(self) -> ClientStats | None:
        return None


class AioHTTPAsyncStreamingAdapter:
    def __init__(self, client: AioHTTPClient) -> None:
        self.client = client

    async def stream(self, case: StreamingCase, url: str) -> StreamingOutcome:
        started_ns = time.perf_counter_ns()
        async with self.client.request("GET", url) as response:
            if case.read == "text":
                return await consume_async_text(
                    _iter_aiohttp_text(response.content, case.chunk_size_bytes),
                    case=case,
                    status_code=int(response.status),
                    started_ns=started_ns,
                )
            if case.read == "lines":
                return await consume_async_lines(
                    _iter_aiohttp_lines(response.content),
                    case=case,
                    status_code=int(response.status),
                    started_ns=started_ns,
                )
            return await consume_async_bytes(
                response.content.iter_chunked(case.chunk_size_bytes),
                case=case,
                status_code=int(response.status),
                started_ns=started_ns,
            )

    async def close(self) -> None:
        await self.client.close()

    def stats(self) -> ClientStats | None:
        return None


async def _consume_async_response(
    response: AsyncStreamResponse,
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    if case.read == "text":
        return await consume_async_text(
            response.aiter_text(),
            case=case,
            status_code=status_code,
            started_ns=started_ns,
        )
    if case.read == "lines":
        return await consume_async_lines(
            response.aiter_lines(),
            case=case,
            status_code=status_code,
            started_ns=started_ns,
        )
    return await consume_async_bytes(
        response.aiter_bytes(),
        case=case,
        status_code=status_code,
        started_ns=started_ns,
    )


def _consume_sync_response(
    response: SyncStreamResponse,
    *,
    case: StreamingCase,
    status_code: int,
    started_ns: int,
) -> StreamingOutcome:
    if case.read == "text":
        return consume_sync_text(
            response.iter_text(),
            case=case,
            status_code=status_code,
            started_ns=started_ns,
        )
    if case.read == "lines":
        return consume_sync_lines(
            response.iter_lines(),
            case=case,
            status_code=status_code,
            started_ns=started_ns,
        )
    return consume_sync_bytes(
        response.iter_bytes(),
        case=case,
        status_code=status_code,
        started_ns=started_ns,
    )


async def _iter_aiohttp_text(content: AioHTTPContent, chunk_size_bytes: int) -> AsyncIterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    async for chunk in content.iter_chunked(chunk_size_bytes):
        if text := decoder.decode(chunk):
            yield text
    if text := decoder.decode(b"", final=True):
        yield text


async def _iter_aiohttp_lines(content: AioHTTPContent) -> AsyncIterator[str]:
    while line := await content.readline():
        yield line.decode("utf-8", errors="strict").rstrip("\r\n")
