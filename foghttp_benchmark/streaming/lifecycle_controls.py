__all__ = (
    "UnsettledWorkers",
    "control_json",
    "run_async_controls",
    "run_sync_controls",
    "wait_quiet",
)

import asyncio
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from http import HTTPStatus
import http.client
import json
import time
from urllib.parse import urlencode, urlsplit
import uuid

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.lifecycle_consume import (
    LifecycleStreamSample,
    async_client,
    consume_async_stream,
    consume_sync_stream,
    expected_body_digest,
    sync_client,
)
from foghttp_benchmark.streaming.lifecycle_models import LifecycleConfig
from foghttp_benchmark.streaming.models import AsyncStreamingAdapter, SyncStreamingAdapter
from foghttp_benchmark.streaming.protocols import AsyncStreamClient


_CONTROL_BODY_LIMIT = 1_048_576


class UnsettledWorkers(TimeoutError):
    """The owning parent must reap this client process without calling client close."""


def control_json(base_url: str, endpoint: str, token: str | None = None) -> JsonObject:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        msg = "Lifecycle control server must be an explicit IPv4 loopback HTTP origin"
        raise ValueError(msg)
    path = endpoint + ("?" + urlencode({"id": token}) if token else "")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(_CONTROL_BODY_LIMIT + 1)
        if response.status != HTTPStatus.OK or len(body) > _CONTROL_BODY_LIMIT:
            msg = f"Lifecycle control request {endpoint} failed: HTTP {response.status}"
            raise RuntimeError(msg)
        value: object = json.loads(body)
        if not isinstance(value, dict):
            msg = "Lifecycle control response is not a JSON object"
            raise TypeError(msg)
        return value
    finally:
        connection.close()


def _tokens(concurrency: int) -> list[str]:
    prefix = uuid.uuid4().hex
    return [f"{prefix}-{index}" for index in range(concurrency)]


def _url(base_url: str, token: str, control: str) -> str:
    return base_url + "/stream?" + urlencode({"id": token, "control": control})


def wait_quiet(
    adapter: AsyncStreamingAdapter | SyncStreamingAdapter,
    base_url: str,
    timeout: float,
) -> JsonObject:
    deadline = time.monotonic() + timeout
    while True:
        server = control_json(base_url, "/summary")
        stats = adapter.stats()
        quiet = stats is None or (stats.get("active_requests") == 0 and stats.get("pending_requests") == 0)
        connections_quiet = (
            stats is None
            or "active_connections" not in stats
            or "idle_connections" not in stats
            or stats["active_connections"] == stats["idle_connections"]
        )
        if server.get("active_requests") == 0 and quiet and connections_quiet:
            return {
                "status": "ok",
                "server_active_requests": 0,
                "client_stats": stats,
                "client_stats_unavailable_reason": (
                    "Comparator has no public lifecycle counters" if stats is None else None
                ),
                "connection_rule": "active_connections includes idle; quiet requires active == idle",
            }
        if time.monotonic() >= deadline:
            msg = f"Lifecycle did not settle within {timeout}s; server={server.get('active_requests')}, client={stats}"
            raise TimeoutError(msg)
        time.sleep(0.01)


def _held_tail_evidence(
    base_url: str,
    tokens: list[str],
    samples: list[LifecycleStreamSample],
    size: int,
) -> JsonObject:
    states = [control_json(base_url, "/state", token) for token in tokens]
    if any(
        state.get("released") is not False
        or state.get("eof_sent") is not False
        or state.get("first_written") is not True
        for state in states
    ):
        msg = "Held-tail control reached release or transport EOF before all client contexts closed"
        raise ValueError(msg)
    if any(not 0 < sample.bytes_read < size or sample.eof or sample.chunks_read != 1 for sample in samples):
        msg = "Held-tail control did not prove unread bytes at explicit client context close"
        raise ValueError(msg)
    return {
        "status": "ok",
        "contexts_closed_before_release": True,
        "state_before_release": states,
        "streams": [sample.payload() for sample in samples],
        "expected_aborts": len(samples),
    }


def _release(base_url: str, tokens: list[str]) -> None:
    for token in tokens:
        control_json(base_url, "/release", token)


def _recovery(samples: list[LifecycleStreamSample]) -> JsonObject:
    return {
        "status": "ok",
        "latencies_ms": [sample.duration_ms for sample in samples],
        "bytes_read_total": sum(sample.bytes_read for sample in samples),
        "streams": [sample.payload() for sample in samples],
    }


def run_sync_controls(
    adapter: SyncStreamingAdapter,
    executor: ThreadPoolExecutor,
    base_url: str,
    config: LifecycleConfig,
    concurrency: int,
) -> JsonObject:
    client = sync_client(adapter)
    digest = expected_body_digest(config.body_bytes)
    tokens = _tokens(concurrency)
    futures = [
        executor.submit(
            consume_sync_stream,
            client,
            _url(base_url, token, "held-tail"),
            body_bytes=config.body_bytes,
            first_chunk=True,
            expected_digest=digest,
        )
        for token in tokens
    ]
    wait(futures)
    try:
        samples = [future.result() for future in futures]
        held_tail = _held_tail_evidence(base_url, tokens, samples, config.body_bytes)
    finally:
        _release(base_url, tokens)
    held_tail["quiescence"] = wait_quiet(adapter, base_url, config.settle_timeout_s)
    recovery = [
        executor.submit(
            consume_sync_stream,
            client,
            _url(base_url, token, "normal"),
            body_bytes=config.body_bytes,
            first_chunk=False,
            expected_digest=digest,
        )
        for token in _tokens(concurrency)
    ]
    wait(recovery)
    cancellation: JsonObject = {
        "status": "unsupported",
        "reason": "Sync worker cancellation is not exposed by the client public API",
    }
    return {
        "held_tail": held_tail,
        "recovery": _recovery([future.result() for future in recovery]),
        "body_wait_cancel": dict(cancellation),
        "slow_consumer_cancel": dict(cancellation),
    }


async def _async_round(
    client: AsyncStreamClient,
    base_url: str,
    config: LifecycleConfig,
    tokens: list[str],
    *,
    control: str,
    first_chunk: bool,
) -> list[LifecycleStreamSample]:
    results = await asyncio.gather(
        *(
            consume_async_stream(
                client,
                _url(base_url, token, control),
                body_bytes=config.body_bytes,
                first_chunk=first_chunk,
                expected_digest=expected_body_digest(config.body_bytes),
            )
            for token in tokens
        ),
        return_exceptions=True,
    )
    samples = []
    for item in results:
        if isinstance(item, BaseException):
            raise item
        samples.append(item)
    return samples


@dataclass(slots=True)
class _CancellationState:
    ready: asyncio.Event
    context_closed: bool = False
    bytes_read: int = 0


async def _cancellable_stream(
    client: AsyncStreamClient,
    url: str,
    state: _CancellationState,
    *,
    slow_consumer: bool,
) -> None:
    try:
        async with client.stream("GET", url) as response:
            if slow_consumer:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        state.bytes_read = len(chunk)
                        state.ready.set()
                        await asyncio.Event().wait()
            else:
                state.ready.set()
                async for chunk in response.aiter_bytes():
                    state.bytes_read += len(chunk)
    finally:
        state.context_closed = True


async def _cancel_and_settle(tasks: list[asyncio.Task[None]], timeout: float) -> float:
    started_ns = time.perf_counter_ns()
    for task in tasks:
        task.cancel()
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        msg = f"{len(pending)} owned streaming workers did not settle after cancellation"
        raise UnsettledWorkers(msg)
    await asyncio.gather(*tasks, return_exceptions=True)
    for task in tasks:
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                raise error
            msg = "Streaming worker completed without observing the requested cancellation"
            raise RuntimeError(msg)
    return (time.perf_counter_ns() - started_ns) / 1_000_000


async def _cancel_control(
    adapter: AsyncStreamingAdapter,
    base_url: str,
    config: LifecycleConfig,
    concurrency: int,
    *,
    slow_consumer: bool,
) -> JsonObject:
    client = async_client(adapter)
    tokens = _tokens(concurrency)
    states = [_CancellationState(asyncio.Event()) for _ in tokens]
    control = "held-tail" if slow_consumer else "body-wait"
    tasks = [
        asyncio.create_task(
            _cancellable_stream(client, _url(base_url, token, control), state, slow_consumer=slow_consumer),
        )
        for token, state in zip(tokens, states, strict=True)
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*(state.ready.wait() for state in states)), config.settle_timeout_s)
        before = await asyncio.to_thread(lambda: [control_json(base_url, "/state", token) for token in tokens])
        if any(
            state.get("headers_sent") is not True
            or state.get("released") is not False
            or state.get("eof_sent") is not False
            or state.get("control") != control
            for state in before
        ):
            msg = "Cancellation control did not reach the declared unreleased server state"
            raise ValueError(msg)
        if not slow_consumer and any(state.bytes_read != 0 for state in states):
            msg = "Body-wait cancellation received bytes before explicit server release"
            raise ValueError(msg)
        if slow_consumer and any(not 0 < state.bytes_read < config.body_bytes for state in states):
            msg = "Slow-consumer cancellation did not retain an unread body tail"
            raise ValueError(msg)
    finally:
        settlement_ms = await _cancel_and_settle(tasks, config.settle_timeout_s)
        await asyncio.to_thread(_release, base_url, tokens)
    if not all(state.context_closed for state in states):
        msg = "A cancelled streaming context remained open"
        raise RuntimeError(msg)
    quiet = await asyncio.to_thread(wait_quiet, adapter, base_url, config.settle_timeout_s)
    recovery = await _async_round(client, base_url, config, _tokens(concurrency), control="normal", first_chunk=False)
    return {
        "status": "ok",
        "deterministic_state": (
            "consumer-paused-after-first-public-bytes" if slow_consumer else "body-read-awaiting-bytes"
        ),
        "owned_workers_cancelled_and_awaited": len(tasks),
        "settlement_ms": settlement_ms,
        "bytes_read": [state.bytes_read for state in states],
        "state_before_cancel": before,
        "quiescence": quiet,
        "recovery": _recovery(recovery),
    }


async def run_async_controls(
    adapter: AsyncStreamingAdapter,
    base_url: str,
    config: LifecycleConfig,
    concurrency: int,
) -> JsonObject:
    client = async_client(adapter)
    tokens = _tokens(concurrency)
    try:
        samples = await _async_round(client, base_url, config, tokens, control="held-tail", first_chunk=True)
        held_tail = await asyncio.to_thread(_held_tail_evidence, base_url, tokens, samples, config.body_bytes)
    finally:
        await asyncio.to_thread(_release, base_url, tokens)
    held_tail["quiescence"] = await asyncio.to_thread(wait_quiet, adapter, base_url, config.settle_timeout_s)
    recovery = await _async_round(client, base_url, config, _tokens(concurrency), control="normal", first_chunk=False)
    return {
        "held_tail": held_tail,
        "recovery": _recovery(recovery),
        "body_wait_cancel": await _cancel_control(adapter, base_url, config, concurrency, slow_consumer=False),
        "slow_consumer_cancel": await _cancel_control(adapter, base_url, config, concurrency, slow_consumer=True),
    }
