__all__ = ("available_one_upstream_clients",)

import importlib
from typing import Protocol

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.one_upstream.cases import (
    DEFAULT_HEADERS,
    DEFAULT_PARAMS,
    FORM_BODY,
    JSON_BODY,
    REQUEST_HEADERS,
    REQUEST_PARAMS,
    all_headers,
    all_params,
)
from foghttp_benchmark.one_upstream.models import (
    AsyncOneUpstreamAdapter,
    OneUpstreamCase,
    OneUpstreamClientConfig,
    OneUpstreamClientFactory,
    OneUpstreamClientSpec,
    SyncOneUpstreamAdapter,
)


INSPECT_ROUTE = "v1/inspect"
EXPECTED_PATH = "/v1/inspect"
EXPECTED_QUERY_ITEMS = (*DEFAULT_PARAMS, *REQUEST_PARAMS)
QUERY_ITEM_LENGTH = 2


class _Response(Protocol):
    def json(self) -> object: ...


class _AsyncClient(Protocol):
    def build_request(self, method: str, url: object, **kwargs: object) -> object: ...

    async def send(self, request: object) -> _Response: ...

    async def request(self, method: str, **kwargs: object) -> _Response: ...

    async def aclose(self) -> None: ...


class _SyncClient(Protocol):
    def build_request(self, method: str, url: object, **kwargs: object) -> object: ...

    def send(self, request: object) -> _Response: ...

    def request(self, method: str, **kwargs: object) -> _Response: ...

    def close(self) -> None: ...


class _AsyncOneUpstreamClientAdapter:
    def __init__(self, client: _AsyncClient) -> None:
        self.client = client

    async def request(self, case: OneUpstreamCase, base_url: str) -> bool:
        kwargs = request_kwargs(case, base_url)
        if case.uses_prepared_request:
            request = self.client.build_request(case.method, kwargs.pop("url"), **kwargs)
            response = await self.client.send(request)
        else:
            response = await self.client.request(case.method, **kwargs)
        return inspect_payload_matches(case, response.json())

    async def close(self) -> None:
        await self.client.aclose()


class _SyncOneUpstreamClientAdapter:
    def __init__(self, client: _SyncClient) -> None:
        self.client = client

    def request(self, case: OneUpstreamCase, base_url: str) -> bool:
        kwargs = request_kwargs(case, base_url)
        if case.uses_prepared_request:
            request = self.client.build_request(case.method, kwargs.pop("url"), **kwargs)
            response = self.client.send(request)
        else:
            response = self.client.request(case.method, **kwargs)
        return inspect_payload_matches(case, response.json())

    def close(self) -> None:
        self.client.close()


def available_one_upstream_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[OneUpstreamClientSpec], dict[str, str]]:
    factories: dict[str, dict[str, OneUpstreamClientFactory]] = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
        },
    }
    clients: list[OneUpstreamClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "one-upstream suite requires comparable client defaults support"
                continue
            try:
                importlib.import_module(client_module_name(name))
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(OneUpstreamClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def make_foghttp_async(config: OneUpstreamClientConfig) -> AsyncOneUpstreamAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.AsyncClient(
        base_url=config.base_url,
        headers=config.headers,
        params=config.params,
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(
            connect=2.0,
            read=10.0,
            write=10.0,
            pool=config.pool_timeout_s,
            total=config.total_timeout_s,
        ),
    )
    return _AsyncOneUpstreamClientAdapter(client)


def make_foghttp_sync(config: OneUpstreamClientConfig) -> SyncOneUpstreamAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.Client(
        base_url=config.base_url,
        headers=config.headers,
        params=config.params,
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(
            connect=2.0,
            read=10.0,
            write=10.0,
            pool=config.pool_timeout_s,
            total=config.total_timeout_s,
        ),
    )
    return _SyncOneUpstreamClientAdapter(client)


def make_httpx_async(config: OneUpstreamClientConfig) -> AsyncOneUpstreamAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.AsyncClient(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _AsyncOneUpstreamClientAdapter(client)


def make_httpx_sync(config: OneUpstreamClientConfig) -> SyncOneUpstreamAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.Client(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _SyncOneUpstreamClientAdapter(client)


def request_kwargs(case: OneUpstreamCase, base_url: str) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "url": request_url(case, base_url),
        "headers": REQUEST_HEADERS if case.uses_defaults else all_headers(),
        "params": REQUEST_PARAMS if case.uses_defaults else all_params(),
    }
    if case.body_kind == "json":
        kwargs["json"] = JSON_BODY
    if case.body_kind == "form":
        kwargs["data"] = FORM_BODY
    return kwargs


def request_url(case: OneUpstreamCase, base_url: str) -> str:
    if case.uses_base_url:
        return INSPECT_ROUTE
    return f"{base_url}/{INSPECT_ROUTE}"


def client_config_for_case(case: OneUpstreamCase, *, base_url: str, concurrency: int) -> OneUpstreamClientConfig:
    return OneUpstreamClientConfig(
        concurrency=concurrency,
        request_limit=concurrency,
        base_url=f"{base_url}/" if case.uses_base_url else None,
        headers=DEFAULT_HEADERS if case.uses_defaults else None,
        params=DEFAULT_PARAMS if case.uses_defaults else None,
    )


def inspect_payload_matches(case: OneUpstreamCase, payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("method") == case.method
        and payload.get("path") == EXPECTED_PATH
        and query_contains_expected(payload.get("query_items"))
        and headers_match(payload.get("headers"))
        and body_matches(case, payload.get("body_text"))
    )


def headers_match(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("accept") == DEFAULT_HEADERS["accept"]
        and value.get("x-client-default") == DEFAULT_HEADERS["x-client-default"]
        and value.get("x-request-case") == REQUEST_HEADERS["x-request-case"]
    )


def body_matches(case: OneUpstreamCase, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if case.body_kind == "json":
        return "Ada Lovelace" in value
    if case.body_kind == "form":
        return all(item in value for item in ("grant_type=client_credentials", "scope=read", "scope=write"))
    return value == ""


def query_contains_expected(value: object) -> bool:
    actual = query_items_from_payload(value)
    if actual is None:
        return False
    return all(item in actual for item in EXPECTED_QUERY_ITEMS)


def query_items_from_payload(value: object) -> list[tuple[str, str]] | None:
    if not isinstance(value, list):
        return None
    actual: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != QUERY_ITEM_LENGTH:
            return None
        key, item_value = item
        if not isinstance(key, str) or not isinstance(item_value, str):
            return None
        actual.append((key, item_value))
    return actual


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
