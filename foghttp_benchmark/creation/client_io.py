__all__ = (
    "close_async_client",
    "close_sync_client",
)

import inspect

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter


async def close_async_client(client: AsyncClientAdapter) -> None:
    close_result = client.close()
    if inspect.isawaitable(close_result):
        await close_result


def close_sync_client(client: SyncClientAdapter) -> None:
    close_result = client.close()
    if inspect.isawaitable(close_result):
        msg = "sync creation benchmark received async close"
        raise TypeError(msg)
