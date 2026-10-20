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
from foghttp_benchmark.streaming.models import (
    AsyncStreamingClientSpec,
    StreamingClientSpec,
    SyncStreamingClientSpec,
)


def available_streaming_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[StreamingClientSpec], dict[str, str]]:
    specs: tuple[StreamingClientSpec, ...] = (
        AsyncStreamingClientSpec(name="foghttp", factory=make_foghttp_async),
        AsyncStreamingClientSpec(name="httpx", factory=make_httpx_async),
        AsyncStreamingClientSpec(name="httpxyz", factory=make_httpxyz_async),
        AsyncStreamingClientSpec(name="aiohttp", factory=make_aiohttp_async),
        SyncStreamingClientSpec(name="foghttp", factory=make_foghttp_sync),
        SyncStreamingClientSpec(name="httpx", factory=make_httpx_sync),
        SyncStreamingClientSpec(name="httpxyz", factory=make_httpxyz_sync),
    )
    specs_by_identity: dict[tuple[str, str], StreamingClientSpec] = {(spec.mode, spec.name): spec for spec in specs}
    clients: list[StreamingClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        if mode not in {ASYNC_MODE, SYNC_MODE}:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            spec = specs_by_identity.get((mode, name))
            if spec is None:
                skipped[f"{mode}:{name}"] = "response-streaming suite requires comparable streaming support"
                continue
            try:
                module = import_client_module(name)
                validate_streaming_support(module, name=name, mode=mode)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(spec)
    return clients, skipped
