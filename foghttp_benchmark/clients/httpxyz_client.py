__all__ = (
    "make_httpxyz_async",
    "make_httpxyz_sync",
)

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.clients.httpx_client import HTTPXAsyncAdapter, HTTPXSyncAdapter
from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.models import ClientConfig


def make_httpxyz_async(config: ClientConfig) -> AsyncClientAdapter:
    httpxyz = import_httpxyz()
    limits = httpxyz.Limits(
        max_connections=config.request_limit,
        max_keepalive_connections=config.idle_connection_limit or config.request_limit,
    )
    timeout = httpxyz.Timeout(connect=2.0, read=10.0, write=10.0, pool=config.pool_timeout_s)
    client = httpxyz.AsyncClient(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXAsyncAdapter(client)


def make_httpxyz_sync(config: ClientConfig) -> SyncClientAdapter:
    httpxyz = import_httpxyz()
    limits = httpxyz.Limits(
        max_connections=config.request_limit,
        max_keepalive_connections=config.idle_connection_limit or config.request_limit,
    )
    timeout = httpxyz.Timeout(connect=2.0, read=10.0, write=10.0, pool=config.pool_timeout_s)
    client = httpxyz.Client(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXSyncAdapter(client)
