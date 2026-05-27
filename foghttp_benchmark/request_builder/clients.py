__all__ = (
    "available_request_builder_clients",
    "client_config_for_case",
    "request_matches_case",
)

import importlib
from typing import Protocol

from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.request_builder.cases import (
    BYTES_BODY,
    DEFAULT_HEADERS,
    DEFAULT_PARAMS,
    JSON_BODY,
    MANY_PARAMS,
    RAW_QUERY,
    REPEATED_PARAMS,
    REQUEST_HEADERS,
    REQUEST_PARAMS,
)
from foghttp_benchmark.request_builder.models import (
    AsyncRequestBuilderAdapter,
    RequestBuilderCase,
    RequestBuilderClientConfig,
    RequestBuilderClientFactory,
    RequestBuilderClientSpec,
    SyncRequestBuilderAdapter,
)


EXPECTED_PATH_PREFIX = "/v1/inspect"
SEND_PATH_PREFIX = "/json-small"


class _Response(Protocol):
    status_code: int


class _AsyncClient(Protocol):
    def build_request(self, method: str, url: object, **kwargs: object) -> object: ...

    async def send(self, request: object) -> _Response: ...

    async def aclose(self) -> None: ...


class _SyncClient(Protocol):
    def build_request(self, method: str, url: object, **kwargs: object) -> object: ...

    def send(self, request: object) -> _Response: ...

    def close(self) -> None: ...


class _AsyncBuilderAdapter:
    def __init__(self, client: _AsyncClient) -> None:
        self.client = client

    def build(self, case: RequestBuilderCase, base_url: str) -> object:
        kwargs = request_kwargs(case, base_url)
        return self.client.build_request(case.method, kwargs.pop("url"), **kwargs)

    async def send(self, request: object) -> int:
        response = await self.client.send(request)
        return response.status_code

    async def close(self) -> None:
        await self.client.aclose()


class _SyncBuilderAdapter:
    def __init__(self, client: _SyncClient) -> None:
        self.client = client

    def build(self, case: RequestBuilderCase, base_url: str) -> object:
        kwargs = request_kwargs(case, base_url)
        return self.client.build_request(case.method, kwargs.pop("url"), **kwargs)

    def send(self, request: object) -> int:
        response = self.client.send(request)
        return response.status_code

    def close(self) -> None:
        self.client.close()


def available_request_builder_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[RequestBuilderClientSpec], dict[str, str]]:
    factories: dict[str, dict[str, RequestBuilderClientFactory]] = {
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
    clients: list[RequestBuilderClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "request-builder suite requires build_request support"
                continue
            try:
                import_client_module(name)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(RequestBuilderClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def make_foghttp_async(config: RequestBuilderClientConfig) -> AsyncRequestBuilderAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.AsyncClient(
        base_url=config.base_url,
        headers=config.headers,
        params=config.params,
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(pool=config.pool_timeout_s),
    )
    return _AsyncBuilderAdapter(client)


def make_foghttp_sync(config: RequestBuilderClientConfig) -> SyncRequestBuilderAdapter:
    foghttp = importlib.import_module("foghttp")
    client = foghttp.Client(
        base_url=config.base_url,
        headers=config.headers,
        params=config.params,
        limits=foghttp.Limits(
            max_active_requests=config.request_limit,
            max_idle_connections_per_host=config.request_limit,
        ),
        timeouts=foghttp.Timeouts(pool=config.pool_timeout_s),
    )
    return _SyncBuilderAdapter(client)


def make_httpx_async(config: RequestBuilderClientConfig) -> AsyncRequestBuilderAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.AsyncClient(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(5.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _AsyncBuilderAdapter(client)


def make_httpx_sync(config: RequestBuilderClientConfig) -> SyncRequestBuilderAdapter:
    httpx = importlib.import_module("httpx")
    client = httpx.Client(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpx.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpx.Timeout(5.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _SyncBuilderAdapter(client)


def make_httpxyz_async(config: RequestBuilderClientConfig) -> AsyncRequestBuilderAdapter:
    httpxyz = import_httpxyz()
    client = httpxyz.AsyncClient(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpxyz.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpxyz.Timeout(5.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _AsyncBuilderAdapter(client)


def make_httpxyz_sync(config: RequestBuilderClientConfig) -> SyncRequestBuilderAdapter:
    httpxyz = import_httpxyz()
    client = httpxyz.Client(
        base_url=config.base_url or "",
        headers=config.headers,
        params=config.params,
        limits=httpxyz.Limits(
            max_connections=config.request_limit,
            max_keepalive_connections=config.request_limit,
        ),
        timeout=httpxyz.Timeout(5.0, pool=config.pool_timeout_s),
        trust_env=False,
    )
    return _SyncBuilderAdapter(client)


def client_config_for_case(case: RequestBuilderCase, *, base_url: str) -> RequestBuilderClientConfig:
    return RequestBuilderClientConfig(
        base_url=f"{base_url}/" if case.uses_base_url else None,
        headers=DEFAULT_HEADERS if case.default_headers else None,
        params=DEFAULT_PARAMS if case.default_params else None,
    )


def request_kwargs(case: RequestBuilderCase, base_url: str) -> dict[str, object]:
    kwargs: dict[str, object] = {"url": request_url(case, base_url)}
    if case.request_headers:
        kwargs["headers"] = REQUEST_HEADERS
    params = params_for_case(case)
    if params is not None:
        kwargs["params"] = params
    if case.body_kind == "json":
        kwargs["json"] = JSON_BODY
    if case.body_kind == "bytes":
        kwargs["content"] = BYTES_BODY
    return kwargs


def request_url(case: RequestBuilderCase, base_url: str) -> str:
    if case.uses_base_url:
        return case.path
    return f"{base_url}/{case.path}"


def params_for_case(case: RequestBuilderCase) -> object | None:
    if case.params_kind == "scalar":
        return REQUEST_PARAMS
    if case.params_kind == "repeated":
        return REPEATED_PARAMS
    if case.params_kind == "raw":
        return RAW_QUERY
    if case.params_kind == "many":
        return MANY_PARAMS
    return None


def request_matches_case(case: RequestBuilderCase, request: object) -> bool:
    url = str(getattr(request, "url", ""))
    return (
        getattr(request, "method", None) == case.method
        and url_matches_case(case, url)
        and headers_match_case(case, getattr(request, "headers", None))
        and body_matches_case(case, getattr(request, "content", None))
    )


def url_matches_case(case: RequestBuilderCase, url: str) -> bool:
    path_prefix = SEND_PATH_PREFIX if case.kind == "send-prepared" else EXPECTED_PATH_PREFIX
    if path_prefix not in url:
        return False
    expected = expected_query_items(case)
    return all(f"{key}={value}" in url for key, value in expected)


def expected_query_items(case: RequestBuilderCase) -> tuple[tuple[str, str], ...]:
    items = DEFAULT_PARAMS if case.default_params else ()
    if case.params_kind == "scalar":
        return (*items, *REQUEST_PARAMS)
    if case.params_kind == "repeated":
        return (*items, *REPEATED_PARAMS)
    if case.params_kind == "raw":
        return (
            ("limit", "10"),
            ("page", "2"),
            ("tag", "rust"),
            ("tag", "python"),
            ("feature", "builder"),
        )
    if case.params_kind == "many":
        return (*items, *MANY_PARAMS)
    return items


def headers_match_case(case: RequestBuilderCase, headers: object) -> bool:
    if not case.default_headers and not case.request_headers:
        return True
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return False
    if case.default_headers and getter("accept") != DEFAULT_HEADERS["accept"]:
        return False
    return not case.request_headers or getter("x-request-case") == REQUEST_HEADERS["x-request-case"]


def body_matches_case(case: RequestBuilderCase, content: object) -> bool:
    if case.body_kind == "json":
        return isinstance(content, bytes) and b"Ada Lovelace" in content
    if case.body_kind == "bytes":
        return isinstance(content, bytes) and len(content) == len(BYTES_BODY)
    return True


def import_client_module(name: str) -> object:
    if name == "httpxyz":
        return import_httpxyz()
    return importlib.import_module(client_module_name(name))


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
