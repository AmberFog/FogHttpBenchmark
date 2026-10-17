import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.lifecycle_server import LifecycleServer


BODY_BYTES = 8192
WRITE_BYTES = 1024


@dataclass(slots=True)
class ServerExchange:
    owner: LifecycleServer
    port: int

    async def open(self, target: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(f"GET {target} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        return reader, writer

    async def json(self, target: str) -> JsonObject:
        reader, writer = await self.open(target)
        try:
            payload: JsonObject = json.loads(await reader.read())
            return payload
        finally:
            writer.close()
            await writer.wait_closed()


@asynccontextmanager
async def owned_server(*, observations: bool) -> AsyncIterator[ServerExchange]:
    owner = LifecycleServer(
        body_bytes=BODY_BYTES,
        write_bytes=WRITE_BYTES,
        identity_header=False,
        collect_body_observations=observations,
    )
    server = await asyncio.start_server(owner.handle, "127.0.0.1", 0)
    try:
        yield ServerExchange(owner, server.sockets[0].getsockname()[1])
    finally:
        server.close()
        await server.wait_closed()
        await owner.close()


async def completed_exchange(*, observations: bool) -> tuple[bytes, JsonObject, JsonObject]:
    async with owned_server(observations=observations) as exchange:
        reader, writer = await exchange.open("/stream?id=normal")
        try:
            body = await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
        return body, await exchange.json("/state"), await exchange.json("/summary")


async def gated_exchange(control: str) -> tuple[JsonObject, JsonObject, bytes, JsonObject]:
    async with owned_server(observations=True) as exchange:
        reader, writer = await exchange.open(f"/stream?id=gated&control={control}")
        first = await reader.readexactly(WRITE_BYTES) if control == "held-tail" else b""
        before = await exchange.json("/state?id=gated")
        try:
            await exchange.json("/release?id=gated")
            body = first + await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
        return before, await exchange.json("/state?id=gated"), body, await exchange.json("/summary")


async def cancelled_exchange() -> tuple[JsonObject, JsonObject, int]:
    async with owned_server(observations=True) as exchange:
        reader, writer = await exchange.open("/stream?id=cancelled&control=held-tail")
        await reader.readexactly(WRITE_BYTES)
        before = await exchange.json("/state?id=cancelled")
        await exchange.owner.close()
        await reader.read()
        writer.close()
        await writer.wait_closed()
        return before, exchange.owner.state("cancelled"), len(exchange.owner.tasks)
