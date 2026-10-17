import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from foghttp_benchmark.models import ClientStats, JsonObject
from foghttp_benchmark.streaming import lifecycle_worker
from foghttp_benchmark.streaming.factories import (
    make_foghttp_async,
    make_foghttp_sync,
    make_httpx_async,
    make_httpx_sync,
)
from foghttp_benchmark.streaming.lifecycle_consume import (
    LifecycleStreamSample,
    consume_async_stream,
    consume_sync_stream,
    expected_body_digest,
)
from foghttp_benchmark.streaming.lifecycle_controls import (
    UnsettledWorkers,
    _cancel_and_settle,
    run_async_controls,
    run_sync_controls,
    wait_quiet,
)
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_server import LifecycleServer
from foghttp_benchmark.streaming.lifecycle_worker import _Worker
from foghttp_benchmark.streaming.models import StreamingClientConfig


BODY = bytes(range(256)) * 32
PUBLIC_CHUNK = 4096
CONTROL_BODY_BYTES = 16_384
IDLE_CONNECTIONS = 3


class Response:
    status_code = 200
    http_version = "HTTP/1.1"

    def __init__(self, chunks: list[bytes], size: int = len(BODY)) -> None:
        self.chunks = chunks
        self.headers = {"content-length": str(size), "content-encoding": "identity"}

    def iter_bytes(self) -> Iterator[bytes]:
        yield from self.chunks

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


class Client:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.closed = False

    @contextmanager
    def stream(self, _method: str, _url: str) -> Iterator[Response]:
        try:
            yield self.response
        finally:
            self.closed = True


class AsyncClient:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.closed = False

    @asynccontextmanager
    async def stream(self, _method: str, _url: str) -> AsyncIterator[Response]:
        try:
            yield self.response
        finally:
            self.closed = True


class StreamCase:
    def __init__(self, chunks: list[bytes], *, asynchronous: bool = False, first_chunk: bool = False) -> None:
        self.asynchronous = asynchronous
        self.first_chunk = first_chunk
        self.response = Response(chunks)
        self.client = AsyncClient(self.response) if asynchronous else Client(self.response)

    def run(self) -> LifecycleStreamSample:
        if isinstance(self.client, AsyncClient):
            return asyncio.run(
                consume_async_stream(
                    self.client,
                    "http://127.0.0.1/stream",
                    body_bytes=len(BODY),
                    first_chunk=self.first_chunk,
                    expected_digest=expected_body_digest(len(BODY)),
                ),
            )
        return consume_sync_stream(
            self.client,
            "http://127.0.0.1/stream",
            body_bytes=len(BODY),
            first_chunk=self.first_chunk,
            expected_digest=expected_body_digest(len(BODY)),
        )


async def _control_case(client_name: str, concurrency: int, mode: str) -> JsonObject:
    config = replace(LifecycleConfig(), body_bytes=CONTROL_BODY_BYTES, server_write_bytes=1024)
    owner = LifecycleServer(body_bytes=config.body_bytes, write_bytes=config.server_write_bytes)
    server = await asyncio.start_server(owner.handle, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    client_config = StreamingClientConfig(concurrency, concurrency, read_timeout_s=2, total_timeout_s=4)
    try:
        if mode == "async":
            adapter = (make_foghttp_async if client_name == "foghttp" else make_httpx_async)(client_config)
            try:
                return await run_async_controls(adapter, url, config, concurrency)
            finally:
                await adapter.close()
        adapter = (make_foghttp_sync if client_name == "foghttp" else make_httpx_sync)(client_config)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            try:
                return await asyncio.to_thread(run_sync_controls, adapter, executor, url, config, concurrency)
            finally:
                await asyncio.to_thread(adapter.close)
    finally:
        server.close()
        await server.wait_closed()
        await owner.close()


def run_control_case(client_name: str, concurrency: int, mode: str) -> JsonObject:
    return asyncio.run(asyncio.wait_for(_control_case(client_name, concurrency, mode), timeout=20))


@dataclass(slots=True)
class QuietAdapter:
    idle_connections: int = IDLE_CONNECTIONS

    def stats(self) -> ClientStats:
        return {
            "active_requests": 0,
            "pending_requests": 0,
            "active_connections": IDLE_CONNECTIONS,
            "idle_connections": self.idle_connections,
        }


def quiet_case(monkeypatch: pytest.MonkeyPatch, idle_connections: int = IDLE_CONNECTIONS) -> JsonObject:
    monkeypatch.setattr(
        "foghttp_benchmark.streaming.lifecycle_controls.control_json",
        lambda *_: {"active_requests": 0},
    )
    return wait_quiet(QuietAdapter(idle_connections), "http://127.0.0.1:1", 0.001)


async def _stubborn_probe() -> tuple[BaseException | None, bool]:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def stubborn_worker() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(stubborn_worker())
    await entered.wait()
    try:
        try:
            await _cancel_and_settle([task], 0.001)
        except UnsettledWorkers as error:
            return error, not task.done()
        else:
            return None, not task.done()
    finally:
        release.set()
        await task


def stubborn_cancellation_probe() -> tuple[BaseException | None, bool]:
    return asyncio.run(_stubborn_probe())


class CloseTrackingAdapter:
    closed = False

    async def close(self) -> None:
        self.closed = True

    def stats(self) -> None:
        return None


async def _empty_batch(*_args: object) -> JsonObject:
    return {"samples": []}


async def _unsettled_controls(*_args: object) -> None:
    msg = "Owned worker deliberately did not settle"
    raise UnsettledWorkers(msg)


def unsettled_worker_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[_Worker, CloseTrackingAdapter]:
    adapter = CloseTrackingAdapter()
    worker = _Worker(
        LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1),
        replace(LifecycleConfig(), warmup_rounds=0, batches=1, rounds_per_batch=1),
        "http://127.0.0.1:1",
        tmp_path,
        tmp_path / "client.json",
    )
    monkeypatch.setattr(lifecycle_worker, "_make_adapter", lambda *_: adapter)
    monkeypatch.setattr(lifecycle_worker, "_async_batch", _empty_batch)
    monkeypatch.setattr(lifecycle_worker, "run_async_controls", _unsettled_controls)
    monkeypatch.setattr(lifecycle_worker, "wait_quiet", lambda *_: {})
    monkeypatch.setattr(_Worker, "mark", lambda *_: None)
    return worker, adapter


def closed_observation_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[_Worker, list[str]]:
    worker = _Worker(
        LifecycleCase(1, "foghttp", "sync", "stream-1m", 1, 1),
        LifecycleConfig(),
        "http://127.0.0.1:1",
        tmp_path,
        tmp_path / "client.json",
    )
    phases: list[str] = []
    monkeypatch.setattr(_Worker, "mark", lambda _self, name: phases.append(name))
    return worker, phases


def metadata_worker_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
    *,
    changed_provenance: bool = False,
) -> JsonObject:
    monkeypatch.setattr(lifecycle_worker, "_run_sync", lambda *_: None)
    observations = iter([None, {"manifest_sha256": "changed"} if changed_provenance else None])
    monkeypatch.setattr(lifecycle_worker, "research_provenance_from_env", lambda: next(observations))
    monkeypatch.setattr(lifecycle_worker, "package_sources", lambda *_: {})
    monkeypatch.setattr(lifecycle_worker.gc, "isenabled", lambda: False)
    monkeypatch.setattr(lifecycle_worker.gc, "get_threshold", lambda: (123, 45, 6))
    monkeypatch.setenv("HTTP_PROXY", "http://private-credentials.example")
    return lifecycle_worker.run_lifecycle_worker(
        LifecycleCase(1, client, "sync", "stream-1m", 1, 1),
        replace(LifecycleConfig(), post_gc=False),
        server_url="http://127.0.0.1:1",
        control_dir=tmp_path,
        output=tmp_path / "metadata-client.json",
    )
