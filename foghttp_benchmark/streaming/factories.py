__all__ = (
    "import_client_module",
    "make_aiohttp_async",
    "make_foghttp_async",
    "make_foghttp_sync",
    "make_httpx_async",
    "make_httpx_sync",
    "make_httpxyz_async",
    "make_httpxyz_sync",
    "validate_streaming_support",
)

import importlib

from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.streaming.adapters import (
    AioHTTPAsyncStreamingAdapter,
    FogHTTPAsyncStreamingAdapter,
    FogHTTPSyncStreamingAdapter,
    HTTPXAsyncStreamingAdapter,
    HTTPXSyncStreamingAdapter,
)
from foghttp_benchmark.streaming.models import (
    AsyncStreamingAdapter,
    StreamingClientConfig,
    SyncStreamingAdapter,
)


def make_foghttp_async(config: StreamingClientConfig) -> AsyncStreamingAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.AsyncClient(
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(
            connect=2.0,
            read=config.read_timeout_s,
            write=10.0,
            pool=config.pool_timeout_s,
            total=config.total_timeout_s,
        ),
    )
    return FogHTTPAsyncStreamingAdapter(client)


def make_foghttp_sync(config: StreamingClientConfig) -> SyncStreamingAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.Client(
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(
            connect=2.0,
            read=config.read_timeout_s,
            write=10.0,
            pool=config.pool_timeout_s,
            total=config.total_timeout_s,
        ),
    )
    return FogHTTPSyncStreamingAdapter(client)


def make_httpx_async(config: StreamingClientConfig) -> AsyncStreamingAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(connect=2.0, read=config.read_timeout_s, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return HTTPXAsyncStreamingAdapter(client)


def make_httpx_sync(config: StreamingClientConfig) -> SyncStreamingAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.Client(
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(connect=2.0, read=config.read_timeout_s, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return HTTPXSyncStreamingAdapter(client)


def make_httpxyz_async(config: StreamingClientConfig) -> AsyncStreamingAdapter:
    httpxyz = import_httpxyz()
    client = httpxyz.AsyncClient(
        limits=httpxyz.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpxyz.Timeout(connect=2.0, read=config.read_timeout_s, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return HTTPXAsyncStreamingAdapter(client)


def make_httpxyz_sync(config: StreamingClientConfig) -> SyncStreamingAdapter:
    httpxyz = import_httpxyz()
    client = httpxyz.Client(
        limits=httpxyz.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpxyz.Timeout(connect=2.0, read=config.read_timeout_s, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return HTTPXSyncStreamingAdapter(client)


def make_aiohttp_async(config: StreamingClientConfig) -> AsyncStreamingAdapter:
    aiohttp = importlib.import_module("aiohttp")
    timeout = aiohttp.ClientTimeout(total=config.total_timeout_s, connect=2.0, sock_read=config.read_timeout_s)
    connector = aiohttp.TCPConnector(
        limit=config.request_limit,
        limit_per_host=config.request_limit,
        ttl_dns_cache=300,
    )
    client = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        trust_env=False,
    )
    return AioHTTPAsyncStreamingAdapter(client)


def validate_streaming_support(module: object, *, name: str, mode: str) -> None:
    if name != "foghttp":
        return
    client_name = "AsyncClient" if mode == ASYNC_MODE else "Client"
    client_type = getattr(module, client_name, None)
    if client_type is None or not hasattr(client_type, "stream"):
        msg = "installed foghttp does not expose response streaming; install foghttp>=0.3.2"
        raise RuntimeError(msg)
    response_name = "AsyncStreamResponse" if mode == ASYNC_MODE else "StreamResponse"
    response_type = getattr(module, response_name, None)
    text_methods = ("aiter_text", "aiter_lines") if mode == ASYNC_MODE else ("iter_text", "iter_lines")
    if response_type is None or any(not hasattr(response_type, method) for method in text_methods):
        msg = "installed foghttp does not expose text/line response streaming; install foghttp>=0.3.2"
        raise RuntimeError(msg)


def import_client_module(name: str) -> object:
    if name == "httpxyz":
        return import_httpxyz()
    return importlib.import_module(client_module_name(name))


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
