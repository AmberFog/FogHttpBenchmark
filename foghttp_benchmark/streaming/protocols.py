__all__ = (
    "AioHTTPClient",
    "AioHTTPContent",
    "AioHTTPRequestContext",
    "AioHTTPResponse",
    "AsyncResponseStream",
    "AsyncStatsStreamClient",
    "AsyncStreamClient",
    "AsyncStreamResponse",
    "SyncResponseStream",
    "SyncStatsStreamClient",
    "SyncStreamClient",
    "SyncStreamResponse",
)

from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import Protocol

from foghttp_benchmark.clients.utils import StatsProvider


class AsyncStreamResponse(Protocol):
    status_code: int

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...

    def aiter_text(self) -> AsyncIterator[str]: ...

    def aiter_lines(self) -> AsyncIterator[str]: ...


class SyncStreamResponse(Protocol):
    status_code: int

    def iter_bytes(self) -> Iterator[bytes]: ...

    def iter_text(self) -> Iterator[str]: ...

    def iter_lines(self) -> Iterator[str]: ...


class AsyncResponseStream(Protocol):
    async def __aenter__(self) -> AsyncStreamResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class SyncResponseStream(Protocol):
    def __enter__(self) -> SyncStreamResponse: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class AsyncStreamClient(Protocol):
    def stream(self, method: str, url: str) -> AsyncResponseStream: ...

    async def aclose(self) -> None: ...


class SyncStreamClient(Protocol):
    def stream(self, method: str, url: str) -> SyncResponseStream: ...

    def close(self) -> None: ...


class AsyncStatsStreamClient(AsyncStreamClient, StatsProvider, Protocol): ...


class SyncStatsStreamClient(SyncStreamClient, StatsProvider, Protocol): ...


class AioHTTPContent(Protocol):
    def iter_chunked(self, n: int) -> AsyncIterator[bytes]: ...

    async def readline(self) -> bytes: ...


class AioHTTPResponse(Protocol):
    status: int
    content: AioHTTPContent


class AioHTTPRequestContext(Protocol):
    async def __aenter__(self) -> AioHTTPResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class AioHTTPClient(Protocol):
    def request(self, method: str, url: str) -> AioHTTPRequestContext: ...

    async def close(self) -> None: ...
