__all__ = ("benchmark_server",)

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from urllib.parse import parse_qsl, urlsplit

from foghttp_benchmark.compressed_response.payloads import COMPRESSED_RESPONSE_BODIES
from foghttp_benchmark.constants import MAX_SPLIT_ONCE
from foghttp_benchmark.scenarios import BYTES_64K, HTTP_REASONS, SMALL_JSON
from foghttp_benchmark.streaming.text_payloads import TEXT_STREAM_CONTENT_TYPE, streaming_text_payloads


MIN_REDIRECT_PATH_PARTS = 2
DRIP_PATH_PARTS = 4
HeaderItems = tuple[tuple[str, str], ...]


@asynccontextmanager
async def benchmark_server() -> AsyncIterator[str]:
    server = await asyncio.start_server(handle_connection, "127.0.0.1", 0)
    sockets = server.sockets
    if not sockets:
        msg = "benchmark server did not bind a socket"
        raise RuntimeError(msg)
    host, port = sockets[0].getsockname()[:2]
    async with server:
        yield f"http://{host}:{port}"


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    keep_alive = True
    try:
        while keep_alive:
            try:
                header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                break

            first_line, headers = parse_request_headers(header_block)
            if not first_line:
                break

            try:
                method, path, _version = first_line.split(" ", MAX_SPLIT_ONCE + 1)
            except ValueError:
                break

            content_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(content_length) if content_length else b""
            keep_alive = headers.get("connection", "").lower() != "close"

            delay_ms = delay_from_path(path)
            if delay_ms is not None:
                await asyncio.sleep(delay_ms / 1000)

            if await write_drip_response(writer, method=method, path=path, keep_alive=keep_alive):
                continue

            status_code, response_body, content_type, extra_headers = build_response(
                method=method,
                path=path,
                headers=headers,
                body=body,
            )
            await write_response(
                writer,
                method=method,
                status_code=status_code,
                body=response_body,
                content_type=content_type,
                keep_alive=keep_alive,
                extra_headers=extra_headers,
            )
    except OSError:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


def parse_request_headers(header_block: bytes) -> tuple[str, dict[str, str]]:
    lines = header_block.decode("latin1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return lines[0], headers


def build_response(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
) -> tuple[int, bytes, bytes, HeaderItems]:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    response = redirect_response(request_path)
    if response is None and request_path.endswith("/inspect"):
        response = 200, inspect_response(method=method, path=path, headers=headers, body=body), b"application/json", ()
    if response is None and request_path == "/json-small":
        response = 200, SMALL_JSON, b"application/json", ()
    bytes_body = bytes_response_body(request_path) if response is None else None
    if response is None and bytes_body is not None:
        response = 200, bytes_body, b"application/octet-stream", ()
    compressed_body = compressed_response_body(request_path) if response is None else None
    if response is None and compressed_body is not None:
        response = compressed_body
    if response is None and request_path == "/echo":
        response = 200, body, b"application/octet-stream", ()
    if response is None and request_path.startswith("/delay/"):
        response = (
            200,
            SMALL_JSON,
            b"application/json",
            (("x-benchmark-delay-ms", request_path.rsplit("/", MAX_SPLIT_ONCE)[1]),),
        )
    return response or (404, b"not found", b"text/plain", ())


def inspect_response(*, method: str, path: str, headers: dict[str, str], body: bytes) -> bytes:
    parts = urlsplit(path)
    payload = {
        "ok": True,
        "method": method,
        "path": parts.path,
        "query_items": parse_qsl(parts.query, keep_blank_values=True),
        "headers": headers,
        "body_text": body.decode("utf-8", errors="replace"),
        "body_size": len(body),
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def bytes_response_body(path: str) -> bytes | None:
    if path == "/bytes-64k":
        return BYTES_64K
    if path.startswith("/bytes/"):
        size = int(path.rsplit("/", MAX_SPLIT_ONCE)[1])
        return b"x" * size
    return None


def compressed_response_body(path: str) -> tuple[int, bytes, bytes, HeaderItems] | None:
    if not path.startswith("/compressed/"):
        return None
    name = path.rsplit("/", MAX_SPLIT_ONCE)[1]
    body = COMPRESSED_RESPONSE_BODIES.get(name)
    if body is None:
        return None
    headers = tuple(("content-encoding", encoding) for encoding in body.content_encoding_headers)
    return 200, body.encoded_body, body.content_type, headers


def delay_from_path(path: str) -> int | None:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    if not request_path.startswith("/delay/"):
        return None
    return int(request_path.rsplit("/", MAX_SPLIT_ONCE)[1])


def redirect_response(path: str) -> tuple[int, bytes, bytes, HeaderItems] | None:
    parts = path.strip("/").split("/")
    if len(parts) < MIN_REDIRECT_PATH_PARTS or parts[0] != "redirect":
        return None

    status_code = int(parts[1])
    target = "/" + "/".join(parts[MIN_REDIRECT_PATH_PARTS:]) if len(parts) > MIN_REDIRECT_PATH_PARTS else "/json-small"
    return status_code, b"", b"text/plain", (("location", target),)


async def write_drip_response(
    writer: asyncio.StreamWriter,
    *,
    method: str,
    path: str,
    keep_alive: bool,
) -> bool:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    parts = request_path.strip("/").split("/")
    if len(parts) != DRIP_PATH_PARTS:
        return False

    if parts[0] == "drip-bytes":
        size = int(parts[1])
        chunk_size = int(parts[2])
        delay_ms = int(parts[3])
        body = b"x" * size
        await write_streaming_response(
            writer,
            method=method,
            status_code=200,
            body=body,
            chunk_size=chunk_size,
            delay_ms=delay_ms,
            content_type=b"application/octet-stream",
            keep_alive=keep_alive,
        )
        return True

    if parts[0] != "drip-text":
        return False

    payload = streaming_text_payloads().get(parts[1])
    if payload is None:
        return False
    chunk_size = int(parts[2])
    delay_ms = int(parts[3])
    await write_streaming_response(
        writer,
        method=method,
        status_code=200,
        body=payload.body,
        chunk_size=chunk_size,
        delay_ms=delay_ms,
        content_type=TEXT_STREAM_CONTENT_TYPE,
        keep_alive=keep_alive,
    )
    return True


async def write_response(
    writer: asyncio.StreamWriter,
    *,
    method: str,
    status_code: int,
    body: bytes,
    content_type: bytes,
    keep_alive: bool,
    extra_headers: HeaderItems,
) -> None:
    response_body = b"" if method == "HEAD" else body
    reason = HTTP_REASONS.get(status_code, "OK")
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        f"content-length: {len(body)}",
        f"content-type: {content_type.decode()}",
        f"connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    headers.extend(f"{name}: {value}" for name, value in extra_headers)
    writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + response_body)
    await writer.drain()


async def write_streaming_response(
    writer: asyncio.StreamWriter,
    *,
    method: str,
    status_code: int,
    body: bytes,
    chunk_size: int,
    delay_ms: int,
    content_type: bytes,
    keep_alive: bool,
) -> None:
    reason = HTTP_REASONS.get(status_code, "OK")
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        f"content-length: {len(body)}",
        f"content-type: {content_type.decode()}",
        f"connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    writer.write("\r\n".join(headers).encode() + b"\r\n\r\n")
    await writer.drain()
    if method == "HEAD":
        return

    for offset in range(0, len(body), chunk_size):
        writer.write(body[offset : offset + chunk_size])
        await writer.drain()
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
