__all__ = ("LifecycleServer", "main")

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import time
from typing import cast
from urllib.parse import parse_qs, urlsplit

from foghttp_benchmark.models import JsonObject


BODY_BYTES = 1024 * 1024
WRITE_BYTES = 64 * 1024
MAX_STREAMS = 20000
HEADER_LIMIT = 65536
MAX_WRITE_DELAY_S = 0.1
HTTP_OK = 200
BODY = bytes(range(256)) * (BODY_BYTES // 256)


@dataclass(slots=True)
class BodyDelivery:
    started_ns: int | None = None
    finished_ns: int | None = None
    write_calls: int = 0
    drain_calls: int = 0
    drains_completed: int = 0
    write_elapsed_ns: int = 0
    drain_elapsed_ns: int = 0
    max_transport_buffer_bytes: int = 0

    async def write(self, writer: asyncio.StreamWriter, chunk: bytes) -> None:
        self.write_calls += 1
        started = time.perf_counter_ns()
        try:
            writer.write(chunk)
        finally:
            self.write_elapsed_ns += time.perf_counter_ns() - started
        self.max_transport_buffer_bytes = max(
            self.max_transport_buffer_bytes,
            writer.transport.get_write_buffer_size(),
        )
        self.drain_calls += 1
        started = time.perf_counter_ns()
        try:
            await writer.drain()
        finally:
            self.drain_elapsed_ns += time.perf_counter_ns() - started
        self.drains_completed += 1

    def payload(self) -> JsonObject:
        return {
            "body_started_ns": self.started_ns,
            "body_finished_ns": self.finished_ns,
            "body_loop_elapsed_ns": (
                self.finished_ns - self.started_ns
                if self.started_ns is not None and self.finished_ns is not None
                else None
            ),
            "write_calls": self.write_calls,
            "drain_calls": self.drain_calls,
            "drains_completed": self.drains_completed,
            "write_elapsed_ns": self.write_elapsed_ns,
            "drain_elapsed_ns": self.drain_elapsed_ns,
            "max_transport_buffer_bytes": self.max_transport_buffer_bytes,
        }


@dataclass(slots=True)
class StreamState:
    token: str
    control: str
    release: asyncio.Event = field(default_factory=asyncio.Event)
    headers_sent: bool = False
    first_written: bool = False
    eof_sent: bool = False
    disconnected: bool = False
    bytes_written: int = 0
    active: bool = True
    body_delivery: BodyDelivery | None = None

    def payload(self) -> JsonObject:
        return {
            "id": self.token,
            "control": self.control,
            "headers_sent": self.headers_sent,
            "first_written": self.first_written,
            "released": self.release.is_set(),
            "eof_sent": self.eof_sent,
            "disconnected": self.disconnected,
            "bytes_written": self.bytes_written,
            "active": self.active,
            "body_delivery": self.body_delivery.payload() if self.body_delivery is not None else None,
        }


class LifecycleServer:
    def __init__(
        self,
        *,
        body_bytes: int = BODY_BYTES,
        write_bytes: int = WRITE_BYTES,
        write_delay_s: float = 0.0,
        identity_header: bool = True,
        collect_body_observations: bool = False,
    ) -> None:
        self.streams: dict[str, StreamState] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.body_bytes = body_bytes
        self.write_bytes = write_bytes
        self.write_delay_s = write_delay_s
        self.identity_header = identity_header
        self.collect_body_observations = collect_body_observations
        self.handler_errors = 0
        self.body = (BODY * ((body_bytes + BODY_BYTES - 1) // BODY_BYTES))[:body_bytes]

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = cast("asyncio.Task[None]", asyncio.current_task())
        self.tasks.add(task)
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            request = header.split(b"\r\n", 1)[0].decode("ascii")
            method, target, protocol = request.split(" ")
            if method != "GET" or protocol != "HTTP/1.1":
                await self._json(writer, {"error": "HTTP/1.1 GET required"}, status=400)
                return
            url = urlsplit(target)
            query = parse_qs(url.query)
            token = query.get("id", [""])[0]
            if url.path == "/stream":
                await self._stream(reader, writer, token, query.get("control", ["normal"])[0])
            elif url.path == "/release" and token in self.streams:
                self.streams[token].release.set()
                await self._json(writer, self.streams[token].payload())
            elif url.path == "/state":
                await self._json(writer, self.state(token))
            elif url.path == "/summary":
                await self._json(writer, self.summary())
            else:
                await self._json(writer, {"error": "unknown endpoint or stream"}, status=404)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, UnicodeError, ValueError):
            self.handler_errors += 1
        except Exception:
            self.handler_errors += 1
            raise
        finally:
            writer.close()
            with suppress(ConnectionError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=1)
            self.tasks.discard(task)

    def state(self, token: str = "") -> JsonObject:
        if token:
            state = self.streams.get(token)
            return state.payload() if state is not None else {"error": "unknown stream"}
        return {
            **self.summary(),
            "streams": {token: state.payload() for token, state in self.streams.items()},
        }

    def summary(self) -> JsonObject:
        return {
            "pid": os.getpid(),
            "body_bytes": self.body_bytes,
            "server_write_bytes": self.write_bytes,
            "server_delay_s": self.write_delay_s,
            "content_encoding": "identity" if self.identity_header else None,
            "body_observations": {
                "enabled": self.collect_body_observations,
                "clock": "time.perf_counter_ns",
                "body_loop_scope": (
                    "First body iteration through final body drain or interrupted exit; includes slicing, "
                    "observer work, configured write delay and held-tail wait; excludes headers and initial body-wait"
                ),
                "write_drain_scope": (
                    "Summed wall time inside each body write and drain; drain includes scheduler and backpressure "
                    "wait, not acknowledgement of receipt; interrupted operations retain elapsed time"
                ),
                "buffer_scope": (
                    "Maximum transport.get_write_buffer_size immediately after body writes; sampled user-space "
                    "transport queue, possibly including earlier headers; excludes kernel/native/client buffers"
                ),
                "observer_cost": (
                    "Additional coroutine call, counters, up to four clock reads and one transport-buffer query "
                    "per body write, plus two loop-bound clock reads; bounded scalars, no per-write sample list"
                ),
                "totals_scope": (
                    "Cumulative completed normal EOF bodies only; per-stream loop times overlap under concurrency; "
                    "maximum buffer is cumulative and must not be differenced between snapshots"
                ),
            },
            "body_delivery_totals": self._body_delivery_totals(),
            "unexpected_errors_total": self.handler_errors,
            "normal_eof_total": sum(state.eof_sent for state in self.streams.values() if state.control == "normal"),
            "normal_disconnected_total": sum(
                state.disconnected for state in self.streams.values() if state.control == "normal"
            ),
            "active_requests": sum(state.active for state in self.streams.values()),
            "requests_total": len(self.streams),
        }

    def _body_delivery_totals(self) -> JsonObject | None:
        if not self.collect_body_observations:
            return None
        deliveries = [
            state.body_delivery
            for state in self.streams.values()
            if state.control == "normal" and state.eof_sent and state.body_delivery is not None
        ]
        return {
            "streams": len(deliveries),
            "body_loop_elapsed_ns": sum(
                delivery.finished_ns - delivery.started_ns
                for delivery in deliveries
                if delivery.finished_ns is not None and delivery.started_ns is not None
            ),
            "write_elapsed_ns": sum(delivery.write_elapsed_ns for delivery in deliveries),
            "drain_elapsed_ns": sum(delivery.drain_elapsed_ns for delivery in deliveries),
            "write_calls": sum(delivery.write_calls for delivery in deliveries),
            "drain_calls": sum(delivery.drain_calls for delivery in deliveries),
            "drains_completed": sum(delivery.drains_completed for delivery in deliveries),
            "max_transport_buffer_bytes": max(
                (delivery.max_transport_buffer_bytes for delivery in deliveries),
                default=0,
            ),
        }

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _json(self, writer: asyncio.StreamWriter, payload: JsonObject, *, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        reason = "OK" if status == HTTP_OK else "Error"
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body,
        )
        await writer.drain()

    async def _stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        token: str,
        control: str,
    ) -> None:
        if not token or token in self.streams or control not in {"normal", "held-tail", "body-wait"}:
            await self._json(writer, {"error": "unique id and supported control required"}, status=400)
            return
        if len(self.streams) >= MAX_STREAMS:
            await self._json(writer, {"error": "bounded server request cap reached"}, status=429)
            return
        delivery = BodyDelivery() if self.collect_body_observations else None
        state = StreamState(token=token, control=control, body_delivery=delivery)
        self.streams[token] = state
        try:
            encoding = "Content-Encoding: identity\r\n" if self.identity_header else ""
            writer.write(
                f"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                f"Content-Length: {self.body_bytes}\r\n{encoding}"
                "Connection: close\r\n\r\n".encode(),
            )
            await writer.drain()
            state.headers_sent = True
            if control == "body-wait":
                await self._wait_release(reader, state)
                if state.disconnected:
                    return
            await self._send_body(reader, writer, state)
        except ConnectionError:
            state.disconnected = True
        finally:
            state.active = False

    async def _send_body(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        state: StreamState,
    ) -> None:
        delivery = state.body_delivery
        try:
            if delivery is not None:
                delivery.started_ns = time.perf_counter_ns()
            for offset in range(0, self.body_bytes, self.write_bytes):
                if offset and self.write_delay_s:
                    await asyncio.sleep(self.write_delay_s)
                chunk = self.body[offset : offset + self.write_bytes]
                if delivery is None:
                    writer.write(chunk)
                    await writer.drain()
                else:
                    await delivery.write(writer, chunk)
                state.bytes_written += len(chunk)
                state.first_written = True
                if state.control == "held-tail" and offset == 0:
                    await self._wait_release(reader, state)
                if state.disconnected:
                    return
            state.eof_sent = True
        finally:
            if delivery is not None and delivery.started_ns is not None:
                delivery.finished_ns = time.perf_counter_ns()

    async def _wait_release(self, reader: asyncio.StreamReader, state: StreamState) -> None:
        disconnect = asyncio.create_task(reader.read(1))
        release = asyncio.create_task(state.release.wait())
        try:
            await asyncio.wait((disconnect, release), return_when=asyncio.FIRST_COMPLETED)
            if disconnect.done():
                state.disconnected = True
            # A disconnected client cannot release the body: the explicit control
            # request following client context exit is the only release barrier.
            await release
            if disconnect.done():
                state.disconnected = True
        finally:
            disconnect.cancel()
            release.cancel()
            await asyncio.gather(disconnect, release, return_exceptions=True)


async def serve(
    ready_file: Path,
    *,
    body_bytes: int = BODY_BYTES,
    write_bytes: int = WRITE_BYTES,
    write_delay_s: float = 0.0,
    identity_header: bool = True,
    collect_body_observations: bool = False,
) -> None:
    owner = LifecycleServer(
        body_bytes=body_bytes,
        write_bytes=write_bytes,
        write_delay_s=write_delay_s,
        identity_header=identity_header,
        collect_body_observations=collect_body_observations,
    )
    server = await asyncio.start_server(owner.handle, "127.0.0.1", 0, limit=HEADER_LIMIT)
    address = server.sockets[0].getsockname()
    ready = {"pid": os.getpid(), "url": f"http://127.0.0.1:{address[1]}"}
    temporary = ready_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(ready), encoding="utf-8")
    temporary.replace(ready_file)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await owner.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Owned local HTTP/1.1 lifecycle server")
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--body-bytes", type=int, default=BODY_BYTES)
    parser.add_argument("--write-bytes", type=int, default=WRITE_BYTES)
    parser.add_argument("--write-delay-s", type=float, default=0.0)
    parser.add_argument("--bytes-measurement", action="store_true")
    parser.add_argument("--no-body-observations", action="store_true")
    args = parser.parse_args()
    if not 0 < args.write_bytes < args.body_bytes <= BODY_BYTES:
        parser.error("Expected 0 < write bytes < body bytes <= 1 MiB")
    if not math.isfinite(args.write_delay_s) or not 0 <= args.write_delay_s <= MAX_WRITE_DELAY_S:
        parser.error("Server write delay must be finite and between 0 and 0.1 seconds")
    asyncio.run(
        serve(
            args.ready_file,
            body_bytes=args.body_bytes,
            write_bytes=args.write_bytes,
            write_delay_s=args.write_delay_s,
            identity_header=not args.bytes_measurement,
            collect_body_observations=args.bytes_measurement and not args.no_body_observations,
        ),
    )


if __name__ == "__main__":
    main()
