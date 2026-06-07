__all__ = ("available_clients",)

import importlib

from foghttp_benchmark.clients.aiohttp_client import make_aiohttp_async
from foghttp_benchmark.clients.foghttp_client import make_foghttp_async, make_foghttp_sync
from foghttp_benchmark.clients.httpx_client import make_httpx_async, make_httpx_sync
from foghttp_benchmark.clients.httpxyz_client import make_httpxyz_async, make_httpxyz_sync
from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.clients.zapros_client import make_zapros_async, make_zapros_sync
from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.models import ClientFactory, ClientSpec


def available_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[ClientSpec], dict[str, str]]:
    factories: dict[str, dict[str, ClientFactory]] = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
            "httpxyz": make_httpxyz_async,
            "aiohttp": make_aiohttp_async,
            "zapros": make_zapros_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
            "httpxyz": make_httpxyz_sync,
            "zapros": make_zapros_sync,
        },
    }
    clients: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "unknown client"
                continue
            try:
                import_client_module(name)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(ClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def import_client_module(name: str) -> object:
    if name == "httpxyz":
        return import_httpxyz()
    return importlib.import_module(client_module_name(name))


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
