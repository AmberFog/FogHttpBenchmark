__all__ = (
    "ZAPROS_PYREQWEST_CLIENT",
    "ZaprosAsyncAdapter",
    "ZaprosSyncAdapter",
    "make_zapros_async",
    "make_zapros_pyreqwest_async",
    "make_zapros_pyreqwest_sync",
    "make_zapros_sync",
)

from datetime import timedelta
import importlib
from threading import Lock
from typing import Any, cast

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.clients.utils import request_kwargs, response_outcome
from foghttp_benchmark.models import ClientConfig, ResponseOutcome, Scenario


ZAPROS_PYREQWEST_CLIENT = "zapros-pyreqwest"
PYREQWEST_HANDLER_FOLLOWS_REDIRECTS = False


class ZaprosAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    async def close(self) -> None:
        await self.client.aclose()


class ZaprosSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any, *, serialize_first_request: bool = False) -> None:
        self.client = client
        self._first_request_lock = Lock()
        self._first_request_done = not serialize_first_request

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        if self._first_request_done:
            return self._request(scenario, url)
        return self._serialized_first_request(scenario, url)

    def _serialized_first_request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        with self._first_request_lock:
            if not self._first_request_done:
                outcome = self._request(scenario, url)
                self._first_request_done = True
                return outcome
        return self._request(scenario, url)

    def _request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    def close(self) -> None:
        self.client.close()


def make_zapros_async(config: ClientConfig) -> AsyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.AsyncStdNetworkHandler(
        total_timeout=config.total_timeout_s,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.per_origin_request_limit or config.request_limit,
        max_idle_connections_per_host=config.idle_connection_limit or config.request_limit,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosAsyncAdapter(zapros.AsyncClient(handler=handler))


def make_zapros_sync(config: ClientConfig) -> SyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.StdNetworkHandler(
        total_timeout=config.total_timeout_s,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.per_origin_request_limit or config.request_limit,
        max_idle_connections_per_host=config.idle_connection_limit or config.request_limit,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosSyncAdapter(zapros.Client(handler=handler))


def make_zapros_pyreqwest_async(config: ClientConfig) -> AsyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.AsyncPyreqwestHandler(client=make_pyreqwest_builder(config, sync=False))
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosAsyncAdapter(zapros.AsyncClient(handler=handler))


def make_zapros_pyreqwest_sync(config: ClientConfig) -> SyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.PyreqwestHandler(client=make_pyreqwest_builder(config, sync=True))
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosSyncAdapter(zapros.Client(handler=handler), serialize_first_request=True)


def make_pyreqwest_builder(config: ClientConfig, *, sync: bool) -> Any:
    pyreqwest_client = cast("Any", importlib.import_module("pyreqwest.client"))
    builder_type = pyreqwest_client.SyncClientBuilder if sync else pyreqwest_client.ClientBuilder
    connection_limit = config.per_origin_request_limit or config.request_limit
    idle_connection_limit = config.idle_connection_limit or config.request_limit
    return (
        builder_type()
        .http1_only()
        .follow_redirects(PYREQWEST_HANDLER_FOLLOWS_REDIRECTS)
        .timeout(timedelta(seconds=config.total_timeout_s))
        .connect_timeout(timedelta(seconds=2.0))
        .read_timeout(timedelta(seconds=10.0))
        .pool_timeout(timedelta(seconds=config.pool_timeout_s))
        .max_connections(connection_limit)
        .pool_max_idle_per_host(idle_connection_limit)
    )
