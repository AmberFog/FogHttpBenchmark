__all__ = ("available_clients",)

import importlib

from foghttp_benchmark.clients.aiohttp_client import make_aiohttp_async
from foghttp_benchmark.clients.foghttp_client import make_foghttp_async, make_foghttp_sync
from foghttp_benchmark.clients.httpx_client import make_httpx_async, make_httpx_sync
from foghttp_benchmark.clients.httpxyz_client import make_httpxyz_async, make_httpxyz_sync
from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.clients.zapros_client import (
    ZAPROS_PYREQWEST_CLIENT,
    make_zapros_async,
    make_zapros_pyreqwest_async,
    make_zapros_pyreqwest_sync,
    make_zapros_sync,
)
from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.models import AsyncClientSpec, ClientSpec, SyncClientSpec


def available_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[ClientSpec], dict[str, str]]:
    specs: tuple[ClientSpec, ...] = (
        AsyncClientSpec(name="foghttp", factory=make_foghttp_async),
        AsyncClientSpec(name="httpx", factory=make_httpx_async),
        AsyncClientSpec(name="httpxyz", factory=make_httpxyz_async),
        AsyncClientSpec(name="aiohttp", factory=make_aiohttp_async),
        AsyncClientSpec(name="zapros", factory=make_zapros_async),
        AsyncClientSpec(name=ZAPROS_PYREQWEST_CLIENT, factory=make_zapros_pyreqwest_async),
        SyncClientSpec(name="foghttp", factory=make_foghttp_sync),
        SyncClientSpec(name="httpx", factory=make_httpx_sync),
        SyncClientSpec(name="httpxyz", factory=make_httpxyz_sync),
        SyncClientSpec(name="zapros", factory=make_zapros_sync),
        SyncClientSpec(name=ZAPROS_PYREQWEST_CLIENT, factory=make_zapros_pyreqwest_sync),
    )
    specs_by_identity: dict[tuple[str, str], ClientSpec] = {(spec.mode, spec.name): spec for spec in specs}
    clients: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        if mode not in {ASYNC_MODE, SYNC_MODE}:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            spec = specs_by_identity.get((mode, name))
            if spec is None:
                skipped[f"{mode}:{name}"] = "unknown client"
                continue
            try:
                import_client_module(name)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(spec)
    return clients, skipped


def import_client_module(name: str) -> object:
    if name == "httpxyz":
        return import_httpxyz()
    if name == ZAPROS_PYREQWEST_CLIENT:
        importlib.import_module("pyreqwest.client")
    return importlib.import_module(client_module_name(name))


def client_module_name(name: str) -> str:
    if name == ZAPROS_PYREQWEST_CLIENT:
        return "zapros"
    return "foghttp" if name == "foghttp" else name
