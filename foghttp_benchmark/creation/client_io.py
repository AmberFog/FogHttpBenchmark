__all__ = (
    "close_async_client",
    "close_sync_client",
    "create_async_client",
    "create_sync_client",
)

import inspect
from typing import cast

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.models import ClientConfig, ClientSpec


def create_async_client(spec: ClientSpec, config: ClientConfig) -> AsyncClientAdapter:
    return cast("AsyncClientAdapter", spec.factory(config))


def create_sync_client(spec: ClientSpec, config: ClientConfig) -> SyncClientAdapter:
    return cast("SyncClientAdapter", spec.factory(config))


async def close_async_client(client: AsyncClientAdapter) -> None:
    close_result = client.close()
    if inspect.isawaitable(close_result):
        await close_result


def close_sync_client(client: SyncClientAdapter) -> None:
    close_result = client.close()
    if inspect.isawaitable(close_result):
        msg = "sync creation benchmark received async close"
        raise TypeError(msg)
