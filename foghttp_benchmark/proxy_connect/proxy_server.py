__all__ = (
    "ProxyEndpoint",
    "ProxyServerStats",
    "benchmark_tls_server",
    "http_proxy_server",
)

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
import shutil
import ssl
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from foghttp_benchmark.constants import BENCHMARK_SERVER_BACKLOG, MAX_SPLIT_ONCE
from foghttp_benchmark.proxy_connect.models import ProxyStatsDelta
from foghttp_benchmark.server import handle_connection, parse_request_headers


HEADER_TIMEOUT_S = 10
PROXY_BUFFER_SIZE = 65_536


@dataclass(frozen=True, slots=True)
class ProxyEndpoint:
    url: str
    stats: "ProxyServerStats"


@dataclass(frozen=True, slots=True)
class TLSEndpoint:
    base_url: str
    ca_cert_path: str


@dataclass(slots=True)
class ProxyRequest:
    method: str
    target: str
    version: str
    headers: dict[str, str]
    body: bytes
    keep_alive: bool


class ProxyServerStats:
    def __init__(self) -> None:
        self.http_requests = 0
        self.connect_requests = 0
        self.proxy_authorization_headers = 0
        self.tunnel_client_bytes = 0
        self.tunnel_upstream_bytes = 0

    def snapshot(self) -> ProxyStatsDelta:
        return ProxyStatsDelta(
            http_requests=self.http_requests,
            connect_requests=self.connect_requests,
            proxy_authorization_headers=self.proxy_authorization_headers,
            tunnel_client_bytes=self.tunnel_client_bytes,
            tunnel_upstream_bytes=self.tunnel_upstream_bytes,
        )


@asynccontextmanager
async def http_proxy_server() -> AsyncIterator[ProxyEndpoint]:
    stats = ProxyServerStats()
    server = await asyncio.start_server(
        lambda reader, writer: handle_proxy_connection(reader, writer, stats),
        "127.0.0.1",
        0,
        backlog=BENCHMARK_SERVER_BACKLOG,
    )
    sockets = server.sockets
    if not sockets:
        msg = "proxy server did not bind a socket"
        raise RuntimeError(msg)
    host, port = sockets[0].getsockname()[:2]
    async with server:
        yield ProxyEndpoint(url=f"http://{host}:{port}", stats=stats)


@asynccontextmanager
async def benchmark_tls_server() -> AsyncIterator[TLSEndpoint]:
    with TemporaryDirectory(prefix="foghttp-benchmark-tls-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        ca_cert_path = temp_dir / "benchmark-ca.crt"
        cert_path = temp_dir / "localhost.crt"
        key_path = temp_dir / "localhost.key"
        generate_localhost_certificate(ca_cert_path=ca_cert_path, cert_path=cert_path, key_path=key_path)
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        server = await asyncio.start_server(
            handle_connection,
            "127.0.0.1",
            0,
            ssl=tls_context,
            backlog=BENCHMARK_SERVER_BACKLOG,
        )
        sockets = server.sockets
        if not sockets:
            msg = "TLS benchmark server did not bind a socket"
            raise RuntimeError(msg)
        _host, port = sockets[0].getsockname()[:2]
        async with server:
            yield TLSEndpoint(base_url=f"https://localhost:{port}", ca_cert_path=str(ca_cert_path))


def generate_localhost_certificate(*, ca_cert_path: Path, cert_path: Path, key_path: Path) -> None:
    openssl_path = shutil.which("openssl")
    if openssl_path is None:
        msg = "proxy-connect suite requires openssl to generate a temporary localhost TLS certificate"
        raise RuntimeError(msg)
    ca_key_path = ca_cert_path.with_suffix(".key")
    csr_path = cert_path.with_suffix(".csr")
    ext_path = cert_path.with_suffix(".ext")
    ext_path.write_text(
        "subjectAltName=DNS:localhost,IP:127.0.0.1\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n",
    )
    ca_command = [
        openssl_path,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-keyout",
        str(ca_key_path),
        "-out",
        str(ca_cert_path),
        "-subj",
        "/CN=FogHTTP Benchmark Local CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    ]
    csr_command = [
        openssl_path,
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(csr_path),
        "-subj",
        "/CN=localhost",
    ]
    sign_command = [
        openssl_path,
        "x509",
        "-req",
        "-in",
        str(csr_path),
        "-CA",
        str(ca_cert_path),
        "-CAkey",
        str(ca_key_path),
        "-CAcreateserial",
        "-out",
        str(cert_path),
        "-days",
        "1",
        "-sha256",
        "-extfile",
        str(ext_path),
    ]
    for command in (ca_command, csr_command, sign_command):
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603 - fixed openssl args, no user input.


async def handle_proxy_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    stats: ProxyServerStats,
) -> None:
    keep_alive = True
    try:
        while keep_alive:
            request = await read_proxy_request(reader)
            if request is None:
                break
            stats.proxy_authorization_headers += int("proxy-authorization" in request.headers)
            if request.method.upper() == "CONNECT":
                await handle_connect_request(request, reader, writer, stats)
                return
            keep_alive = request.keep_alive
            await handle_http_proxy_request(request, writer, stats)
    except OSError:
        pass
    finally:
        await close_writer(writer)


async def read_proxy_request(reader: asyncio.StreamReader) -> ProxyRequest | None:
    try:
        header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=HEADER_TIMEOUT_S)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        return None
    first_line, headers = parse_request_headers(header_block)
    if not first_line:
        return None
    try:
        method, target, version = first_line.split(" ", MAX_SPLIT_ONCE + 1)
    except ValueError:
        return None
    content_length = int(headers.get("content-length", "0"))
    body = await reader.readexactly(content_length) if content_length else b""
    connection_header = headers.get("proxy-connection") or headers.get("connection", "")
    return ProxyRequest(
        method=method,
        target=target,
        version=version,
        headers=headers,
        body=body,
        keep_alive=connection_header.lower() != "close",
    )


async def handle_http_proxy_request(
    request: ProxyRequest,
    client_writer: asyncio.StreamWriter,
    stats: ProxyServerStats,
) -> None:
    stats.http_requests += 1
    target = urlsplit(request.target)
    if target.scheme.lower() != "http" or target.hostname is None:
        await write_proxy_error(client_writer, 400, "Bad Request")
        return
    target_port = target.port or 80
    target_path = target.path or "/"
    if target.query:
        target_path = f"{target_path}?{target.query}"
    try:
        origin_reader, origin_writer = await asyncio.open_connection(target.hostname, target_port)
    except OSError:
        await write_proxy_error(client_writer, 502, "Bad Gateway")
        return

    try:
        origin_writer.write(proxy_origin_request(request, host=target.netloc, path=target_path))
        await origin_writer.drain()
        response = await read_origin_response(origin_reader)
        client_writer.write(response)
        await client_writer.drain()
    finally:
        await close_writer(origin_writer)


def proxy_origin_request(request: ProxyRequest, *, host: str, path: str) -> bytes:
    header_lines = [f"{request.method} {path} {request.version}", f"host: {host}"]
    for name, value in request.headers.items():
        if name in {"host", "proxy-authorization", "proxy-connection"}:
            continue
        header_lines.append(f"{name}: {value}")
    return "\r\n".join(header_lines).encode("latin1") + b"\r\n\r\n" + request.body


async def read_origin_response(reader: asyncio.StreamReader) -> bytes:
    header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=HEADER_TIMEOUT_S)
    _first_line, headers = parse_request_headers(header_block)
    content_length = int(headers.get("content-length", "0"))
    body = await reader.readexactly(content_length) if content_length else b""
    return header_block + body


async def handle_connect_request(
    request: ProxyRequest,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    stats: ProxyServerStats,
) -> None:
    stats.connect_requests += 1
    host, port = connect_authority(request.target)
    if host is None or port is None:
        await write_proxy_error(client_writer, 400, "Bad Request")
        return
    try:
        origin_reader, origin_writer = await asyncio.open_connection(host, port)
    except OSError:
        await write_proxy_error(client_writer, 502, "Bad Gateway")
        return

    client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await client_writer.drain()
    await tunnel_streams(
        client_reader=client_reader,
        client_writer=client_writer,
        origin_reader=origin_reader,
        origin_writer=origin_writer,
        stats=stats,
    )


def connect_authority(value: str) -> tuple[str | None, int | None]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        return None, None
    try:
        return host.strip("[]"), int(port_text)
    except ValueError:
        return None, None


async def tunnel_streams(
    *,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    origin_reader: asyncio.StreamReader,
    origin_writer: asyncio.StreamWriter,
    stats: ProxyServerStats,
) -> None:
    async def pipe(
        source: asyncio.StreamReader,
        destination: asyncio.StreamWriter,
        *,
        direction: str,
    ) -> None:
        try:
            while chunk := await source.read(PROXY_BUFFER_SIZE):
                if direction == "client":
                    stats.tunnel_client_bytes += len(chunk)
                else:
                    stats.tunnel_upstream_bytes += len(chunk)
                destination.write(chunk)
                await destination.drain()
        except OSError:
            pass
        finally:
            await close_writer(destination)

    await asyncio.gather(
        pipe(client_reader, origin_writer, direction="client"),
        pipe(origin_reader, client_writer, direction="upstream"),
        return_exceptions=True,
    )


async def write_proxy_error(writer: asyncio.StreamWriter, status_code: int, reason: str) -> None:
    body = reason.encode()
    writer.write(
        (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            f"content-length: {len(body)}\r\n"
            "content-type: text/plain\r\n"
            "connection: close\r\n"
            "\r\n"
        ).encode("latin1")
        + body,
    )
    await writer.drain()


async def close_writer(writer: asyncio.StreamWriter) -> None:
    if not writer.is_closing():
        writer.close()
    with suppress(OSError):
        await writer.wait_closed()
