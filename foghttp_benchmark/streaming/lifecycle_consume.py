__all__ = (
    "LifecycleStreamSample",
    "async_client",
    "consume_async_stream",
    "consume_sync_stream",
    "expected_body_digest",
    "sync_client",
)

from dataclasses import asdict, dataclass
import hashlib
from http import HTTPStatus
import time

from foghttp_benchmark.streaming.adapters import (
    FogHTTPAsyncStreamingAdapter,
    FogHTTPSyncStreamingAdapter,
    HTTPXAsyncStreamingAdapter,
    HTTPXSyncStreamingAdapter,
)
from foghttp_benchmark.streaming.bytes_payloads import streaming_bytes_sha256
from foghttp_benchmark.streaming.models import AsyncStreamingAdapter, SyncStreamingAdapter
from foghttp_benchmark.streaming.protocols import (
    AsyncStreamClient,
    AsyncStreamResponse,
    SyncStreamClient,
    SyncStreamResponse,
)


@dataclass(frozen=True, slots=True)
class LifecycleStreamSample:
    duration_ms: float
    first_item_ms: float | None
    close_return_ms: float
    bytes_read: int
    chunks_read: int
    first_chunk_bytes: int | None
    eof: bool
    status_code: int
    content_length: str | None
    content_encoding: str | None
    transfer_encoding: str | None
    http_version: str | None
    sha256: str

    def payload(self) -> dict[str, object]:
        return asdict(self)


def sync_client(adapter: SyncStreamingAdapter) -> SyncStreamClient:
    if isinstance(adapter, FogHTTPSyncStreamingAdapter | HTTPXSyncStreamingAdapter):
        return adapter.client
    msg = "Lifecycle profile requires an explicit FogHTTP or HTTPX sync client"
    raise TypeError(msg)


def async_client(adapter: AsyncStreamingAdapter) -> AsyncStreamClient:
    if isinstance(adapter, FogHTTPAsyncStreamingAdapter | HTTPXAsyncStreamingAdapter):
        return adapter.client
    msg = "Lifecycle profile requires an explicit FogHTTP or HTTPX async client"
    raise TypeError(msg)


def expected_body_digest(size: int) -> str:
    return streaming_bytes_sha256(size)


def _header(response: SyncStreamResponse | AsyncStreamResponse, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return str(value) if value is not None else None


def _sample(
    response: SyncStreamResponse | AsyncStreamResponse,
    *,
    started_ns: int,
    close_started_ns: int,
    finished_ns: int,
    first_item_ms: float | None,
    bytes_read: int,
    chunks_read: int,
    first_chunk_bytes: int | None,
    eof: bool,
    digest: str,
) -> LifecycleStreamSample:
    return LifecycleStreamSample(
        duration_ms=(finished_ns - started_ns) / 1_000_000,
        first_item_ms=first_item_ms,
        close_return_ms=(finished_ns - close_started_ns) / 1_000_000,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_bytes=first_chunk_bytes,
        eof=eof,
        status_code=int(response.status_code),
        content_length=_header(response, "content-length"),
        content_encoding=_header(response, "content-encoding"),
        transfer_encoding=_header(response, "transfer-encoding"),
        http_version=str(value) if (value := getattr(response, "http_version", None)) is not None else None,
        sha256=digest,
    )


def _validate(sample: LifecycleStreamSample, *, body_bytes: int, first_chunk: bool, digest: str) -> None:
    if sample.status_code != HTTPStatus.OK or sample.content_length != str(body_bytes):
        msg = "Lifecycle response status or Content-Length differs from the declared workload"
        raise ValueError(msg)
    if sample.transfer_encoding is not None or sample.http_version not in {"HTTP/1.1", "1.1"}:
        msg = "Lifecycle response must use HTTP/1.1 Content-Length framing"
        raise ValueError(msg)
    if sample.content_encoding not in {None, "identity"}:
        msg = "Lifecycle responses must be uncompressed"
        raise ValueError(msg)
    if not 0 < sample.bytes_read <= body_bytes or sample.first_chunk_bytes is None:
        msg = "Lifecycle response did not deliver a nonempty public bytes chunk"
        raise ValueError(msg)
    if first_chunk and sample.sha256 != expected_body_digest(sample.bytes_read):
        msg = "Lifecycle first chunk failed deterministic prefix integrity validation"
        raise ValueError(msg)
    if not first_chunk and (not sample.eof or sample.bytes_read != body_bytes or sample.sha256 != digest):
        msg = "Lifecycle EOF response failed complete-body integrity validation"
        raise ValueError(msg)


def consume_sync_stream(
    client: SyncStreamClient,
    url: str,
    *,
    body_bytes: int,
    first_chunk: bool,
    expected_digest: str,
) -> LifecycleStreamSample:
    bytes_read = chunks_read = 0
    first_item_ms = None
    first_chunk_bytes = None
    eof = False
    digest = hashlib.sha256()
    started_ns = time.perf_counter_ns()
    with client.stream("GET", url) as response:
        for chunk in response.iter_bytes():
            if not chunk:
                continue
            if first_item_ms is None:
                first_item_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
                first_chunk_bytes = len(chunk)
            bytes_read += len(chunk)
            chunks_read += 1
            digest.update(chunk)
            if first_chunk:
                break
        else:
            eof = True
        close_started_ns = time.perf_counter_ns()
    finished_ns = time.perf_counter_ns()
    result = _sample(
        response,
        started_ns=started_ns,
        close_started_ns=close_started_ns,
        finished_ns=finished_ns,
        first_item_ms=first_item_ms,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_bytes=first_chunk_bytes,
        eof=eof,
        digest=digest.hexdigest(),
    )
    _validate(result, body_bytes=body_bytes, first_chunk=first_chunk, digest=expected_digest)
    return result


async def consume_async_stream(
    client: AsyncStreamClient,
    url: str,
    *,
    body_bytes: int,
    first_chunk: bool,
    expected_digest: str,
) -> LifecycleStreamSample:
    bytes_read = chunks_read = 0
    first_item_ms = None
    first_chunk_bytes = None
    eof = False
    digest = hashlib.sha256()
    started_ns = time.perf_counter_ns()
    async with client.stream("GET", url) as response:
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            if first_item_ms is None:
                first_item_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
                first_chunk_bytes = len(chunk)
            bytes_read += len(chunk)
            chunks_read += 1
            digest.update(chunk)
            if first_chunk:
                break
        else:
            eof = True
        close_started_ns = time.perf_counter_ns()
    finished_ns = time.perf_counter_ns()
    result = _sample(
        response,
        started_ns=started_ns,
        close_started_ns=close_started_ns,
        finished_ns=finished_ns,
        first_item_ms=first_item_ms,
        bytes_read=bytes_read,
        chunks_read=chunks_read,
        first_chunk_bytes=first_chunk_bytes,
        eof=eof,
        digest=digest.hexdigest(),
    )
    _validate(result, body_bytes=body_bytes, first_chunk=first_chunk, digest=expected_digest)
    return result
