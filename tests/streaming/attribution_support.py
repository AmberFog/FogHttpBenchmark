import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.attribution_consume import ObservationBudget, PendingStream, consume_attribution_stream
from foghttp_benchmark.streaming.attribution_measure import measure_async_batch
from foghttp_benchmark.streaming.attribution_models import AttributionConfig


BODY = bytes(range(32))


@dataclass
class AttributionResponse:
    chunks: list[bytes]
    status_code: int = 200
    http_version: str = "HTTP/1.1"
    headers: dict[str, str] = field(default_factory=lambda: {"content-length": str(len(BODY))})
    error_after_chunks: Exception | None = None
    read_requests: list[int | None] = field(default_factory=list)

    async def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        self.read_requests.append(chunk_size)
        for chunk in self.chunks:
            yield chunk
        if self.error_after_chunks is not None:
            raise self.error_after_chunks

    async def aiter_text(self) -> AsyncIterator[str]:
        msg = "Bytes measurement must never request text"
        raise AssertionError(msg)
        yield ""  # pragma: no cover

    async def aiter_lines(self) -> AsyncIterator[str]:
        msg = "Bytes measurement must never request lines"
        raise AssertionError(msg)
        yield ""  # pragma: no cover


@dataclass
class AttributionClient:
    response: AttributionResponse
    closed_contexts: int = 0

    @asynccontextmanager
    async def stream(self, _method: str, _url: str) -> AsyncIterator[AttributionResponse]:
        try:
            yield self.response
        finally:
            self.closed_contexts += 1

    async def aclose(self) -> None:
        pass


def collect(
    client: AttributionClient,
    config: AttributionConfig | None = None,
    budget: ObservationBudget | None = None,
) -> PendingStream:
    return asyncio.run(
        consume_attribution_stream(
            client,
            "http://127.0.0.1/stream",
            body_bytes=len(BODY),
            stream=1,
            config=config or AttributionConfig(),
            budget=budget,
        ),
    )


def finalized(client: AttributionClient, config: AttributionConfig | None = None) -> JsonObject:
    return collect(client, config).finalize(body_bytes=len(BODY), expected_digest=hashlib.sha256(BODY).hexdigest())


def measured(client: AttributionClient, config: AttributionConfig | None = None) -> JsonObject:
    return asyncio.run(
        measure_async_batch(
            client,
            "http://127.0.0.1/stream",
            body_bytes=len(BODY),
            concurrency=1,
            rounds=1,
            config=config or AttributionConfig(),
            server_pid=999_999_999,
            batch=1,
        ),
    )
