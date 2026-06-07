__all__ = ("available_proxy_connect_clients",)

import importlib
import ssl
from typing import Any, Protocol, cast

from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.clients.utils import StatsProvider, json_has_keys, stats_from_client
from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.proxy_connect.models import (
    AsyncProxyConnectAdapter,
    ProxyConnectCase,
    ProxyConnectClientConfig,
    ProxyConnectClientFactory,
    ProxyConnectClientSpec,
    SyncProxyConnectAdapter,
)


EXPECTED_JSON_KEYS = ("ok",)
HTTP_OK = 200


class _Response(Protocol):
    status_code: int

    def json(self) -> object: ...


class _AsyncClient(Protocol):
    async def request(self, method: str, url: str) -> _Response: ...

    async def aclose(self) -> None: ...


class _SyncClient(Protocol):
    def request(self, method: str, url: str) -> _Response: ...

    def close(self) -> None: ...


class _AsyncReusedProxyAdapter:
    def __init__(self, client: _AsyncClient) -> None:
        self.client = client

    async def request(self, _case: ProxyConnectCase, url: str) -> bool:
        response = await self.client.request("GET", url)
        return response_matches(response)

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> ClientStats | None:
        return optional_stats_from_client(self.client)


class _SyncReusedProxyAdapter:
    def __init__(self, client: _SyncClient) -> None:
        self.client = client

    def request(self, _case: ProxyConnectCase, url: str) -> bool:
        response = self.client.request("GET", url)
        return response_matches(response)

    def close(self) -> None:
        self.client.close()

    def stats(self) -> ClientStats | None:
        return optional_stats_from_client(self.client)


class _AsyncColdProxyAdapter:
    def __init__(self, factory: "AsyncClientBuilder") -> None:
        self.factory = factory

    async def request(self, _case: ProxyConnectCase, url: str) -> bool:
        client = self.factory()
        try:
            response = await client.request("GET", url)
            return response_matches(response)
        finally:
            await client.aclose()

    async def close(self) -> None:
        return None

    def stats(self) -> ClientStats | None:
        return None


class _SyncColdProxyAdapter:
    def __init__(self, factory: "SyncClientBuilder") -> None:
        self.factory = factory

    def request(self, _case: ProxyConnectCase, url: str) -> bool:
        client = self.factory()
        try:
            response = client.request("GET", url)
            return response_matches(response)
        finally:
            client.close()

    def close(self) -> None:
        return None

    def stats(self) -> ClientStats | None:
        return None


class AsyncClientBuilder(Protocol):
    def __call__(self) -> _AsyncClient: ...


class SyncClientBuilder(Protocol):
    def __call__(self) -> _SyncClient: ...


def available_proxy_connect_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[ProxyConnectClientSpec], dict[str, str]]:
    factories: dict[str, dict[str, ProxyConnectClientFactory]] = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
            "httpxyz": make_httpxyz_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
            "httpxyz": make_httpxyz_sync,
        },
    }
    clients: list[ProxyConnectClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "proxy-connect suite requires comparable client-level proxy support"
                continue
            try:
                import_client_module(name)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(ProxyConnectClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def make_foghttp_async(config: ProxyConnectClientConfig) -> AsyncProxyConnectAdapter:
    foghttp = importlib.import_module("foghttp")

    def factory() -> _AsyncClient:
        return cast("_AsyncClient", foghttp.AsyncClient(**foghttp_client_kwargs(foghttp, config)))

    if config.lifecycle == "cold-client":
        return _AsyncColdProxyAdapter(factory)
    return _AsyncReusedProxyAdapter(factory())


def make_foghttp_sync(config: ProxyConnectClientConfig) -> SyncProxyConnectAdapter:
    foghttp = importlib.import_module("foghttp")

    def factory() -> _SyncClient:
        return cast("_SyncClient", foghttp.Client(**foghttp_client_kwargs(foghttp, config)))

    if config.lifecycle == "cold-client":
        return _SyncColdProxyAdapter(factory)
    return _SyncReusedProxyAdapter(factory())


def foghttp_client_kwargs(foghttp: Any, config: ProxyConnectClientConfig) -> dict[str, object]:
    return {
        "limits": foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        "timeouts": foghttp.Timeouts(
            connect=2.0,
            read=10.0,
            write=10.0,
            pool=config.pool_timeout_s,
            total=config.total_timeout_s,
        ),
        "proxy": explicit_proxy(config),
        "trust_env": config.config == "trust-env",
        "tls": foghttp.TLSConfig(ca_certificates=config.ca_cert_path, trust_webpki_roots=False),
    }


def make_httpx_async(config: ProxyConnectClientConfig) -> AsyncProxyConnectAdapter:
    httpx = importlib.import_module("httpx")

    def factory() -> _AsyncClient:
        return cast("_AsyncClient", httpx.AsyncClient(**httpx_client_kwargs(httpx, config)))

    if config.lifecycle == "cold-client":
        return _AsyncColdProxyAdapter(factory)
    return _AsyncReusedProxyAdapter(factory())


def make_httpx_sync(config: ProxyConnectClientConfig) -> SyncProxyConnectAdapter:
    httpx = importlib.import_module("httpx")

    def factory() -> _SyncClient:
        return cast("_SyncClient", httpx.Client(**httpx_client_kwargs(httpx, config)))

    if config.lifecycle == "cold-client":
        return _SyncColdProxyAdapter(factory)
    return _SyncReusedProxyAdapter(factory())


def make_httpxyz_async(config: ProxyConnectClientConfig) -> AsyncProxyConnectAdapter:
    httpxyz = import_httpxyz()

    def factory() -> _AsyncClient:
        return cast("_AsyncClient", httpxyz.AsyncClient(**httpx_client_kwargs(httpxyz, config)))

    if config.lifecycle == "cold-client":
        return _AsyncColdProxyAdapter(factory)
    return _AsyncReusedProxyAdapter(factory())


def make_httpxyz_sync(config: ProxyConnectClientConfig) -> SyncProxyConnectAdapter:
    httpxyz = import_httpxyz()

    def factory() -> _SyncClient:
        return cast("_SyncClient", httpxyz.Client(**httpx_client_kwargs(httpxyz, config)))

    if config.lifecycle == "cold-client":
        return _SyncColdProxyAdapter(factory)
    return _SyncReusedProxyAdapter(factory())


def httpx_client_kwargs(client_module: Any, config: ProxyConnectClientConfig) -> dict[str, object]:
    return {
        "limits": client_module.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        "timeout": client_module.Timeout(connect=2.0, read=10.0, write=10.0, pool=config.pool_timeout_s),
        "proxy": explicit_proxy(config),
        "trust_env": config.config == "trust-env",
        "verify": ssl.create_default_context(cafile=config.ca_cert_path),
    }


def explicit_proxy(config: ProxyConnectClientConfig) -> str | None:
    return config.proxy_url if config.config == "explicit" else None


def response_matches(response: _Response) -> bool:
    return int(response.status_code) == HTTP_OK and json_has_keys(response.json(), EXPECTED_JSON_KEYS)


def optional_stats_from_client(client: object) -> ClientStats | None:
    stats_method = getattr(client, "stats", None)
    if not callable(stats_method):
        return None
    return stats_from_client(cast("StatsProvider", client))


def import_client_module(name: str) -> object:
    if name == "httpxyz":
        return import_httpxyz()
    return importlib.import_module(client_module_name(name))


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
