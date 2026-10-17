__all__ = ("run_installation_smoke",)

import asyncio
import hashlib
from importlib.metadata import version

from foghttp import AsyncClient

from foghttp_benchmark.models import JsonObject


HTTP_OK = 200


async def run_installation_smoke() -> JsonObject:
    payload = bytes(range(256)) * 257
    expected = hashlib.sha256(payload).hexdigest()
    finished = asyncio.Event()

    async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            writer.write(
                f"HTTP/1.1 200 OK\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode(),
            )
            for offset in range(0, len(payload), 8192):
                writer.write(payload[offset : offset + 8192])
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()

    digest = hashlib.sha256()
    count = 0
    async with await asyncio.start_server(respond, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with asyncio.timeout(20), AsyncClient(trust_env=False) as client:
            async with client.stream("GET", f"http://127.0.0.1:{port}/bytes") as response:
                if response.status_code != HTTP_OK:
                    msg = "Installed-wheel HTTP smoke returned an unexpected status"
                    raise ValueError(msg)
                async for chunk in response.aiter_bytes():
                    count += len(chunk)
                    digest.update(chunk)
            await asyncio.wait_for(finished.wait(), timeout=10)
    if count != len(payload) or digest.hexdigest() != expected:
        msg = "Installed-wheel streaming smoke failed byte-count or integrity verification"
        raise ValueError(msg)
    return {
        "kind": "installation-correctness-smoke",
        "foghttp": version("foghttp"),
        "bytes": count,
        "sha256": expected,
        "eof": True,
    }
