__all__ = ("available_streaming_clients",)

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.streaming.factories import (
    import_client_module,
    make_aiohttp_async,
    make_foghttp_async,
    make_foghttp_sync,
    make_httpx_async,
    make_httpx_sync,
    make_httpxyz_async,
    make_httpxyz_sync,
    validate_streaming_support,
)
from foghttp_benchmark.streaming.models import StreamingClientFactory, StreamingClientSpec


def available_streaming_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[StreamingClientSpec], dict[str, str]]:
    factories: dict[str, dict[str, StreamingClientFactory]] = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
            "httpxyz": make_httpxyz_async,
            "aiohttp": make_aiohttp_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
            "httpxyz": make_httpxyz_sync,
        },
    }
    clients: list[StreamingClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "response-streaming suite requires comparable streaming support"
                continue
            try:
                module = import_client_module(name)
                validate_streaming_support(module, name=name, mode=mode)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(StreamingClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped
