from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from tests.streaming.attribution_support import BODY, AttributionResponse


@dataclass
class WindowClock:
    step_ns: int = 100_000_000
    now_ns: int = 0

    def __call__(self) -> int:
        return self.now_ns


@dataclass
class ClockedResponse(AttributionResponse):
    clock: WindowClock | None = None

    async def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        self.read_requests.append(chunk_size)
        for chunk in self.chunks:
            if self.clock is not None:
                self.clock.now_ns += self.clock.step_ns
            yield chunk


@dataclass
class WindowClient:
    clock: WindowClock
    corrupt_stream: int | None = None
    chunk_bytes: int | None = None
    streams: int = 0
    closed_contexts: int = 0

    @asynccontextmanager
    async def stream(self, _method: str, _url: str) -> AsyncIterator[AttributionResponse]:
        self.streams += 1
        payload = b"x" * len(BODY) if self.streams == self.corrupt_stream else BODY
        size = self.chunk_bytes or len(payload)
        chunks = [payload[offset : offset + size] for offset in range(0, len(payload), size)]
        try:
            yield ClockedResponse(chunks, clock=self.clock)
        finally:
            self.closed_contexts += 1

    async def aclose(self) -> None:
        pass
