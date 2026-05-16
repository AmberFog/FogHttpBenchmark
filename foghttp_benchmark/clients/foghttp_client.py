__all__ = (
    "FogHTTPAsyncAdapter",
    "FogHTTPSyncAdapter",
    "make_foghttp_async",
    "make_foghttp_sync",
)

import importlib
from typing import Any

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.clients.utils import request_kwargs, response_outcome, stats_from_client
from foghttp_benchmark.models import ClientConfig, ResponseOutcome, Scenario


class FogHTTPAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=response.url,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


class FogHTTPSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=response.url,
        )

    def close(self) -> None:
        self.client.close()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


def make_foghttp_async(config: ClientConfig) -> AsyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(
        connect=2.0,
        read=10.0,
        write=10.0,
        pool=config.pool_timeout_s,
        total=config.total_timeout_s,
    )
    client = foghttp.AsyncClient(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
        runtime_workers=config.runtime_workers,
    )
    return FogHTTPAsyncAdapter(client)


def make_foghttp_sync(config: ClientConfig) -> SyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(
        connect=2.0,
        read=10.0,
        write=10.0,
        pool=config.pool_timeout_s,
        total=config.total_timeout_s,
    )
    client = foghttp.Client(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
        runtime_workers=config.runtime_workers,
    )
    return FogHTTPSyncAdapter(client)


def foghttp_limits(foghttp: Any, config: ClientConfig) -> Any:
    max_pending_requests = config.max_pending_requests
    if max_pending_requests is None:
        max_pending_requests = max(config.request_limit * 10, config.concurrency)
    idle_connection_limit = config.idle_connection_limit
    if idle_connection_limit is None:
        idle_connection_limit = max(config.request_limit, 1)
    return foghttp.Limits(
        max_active_requests=config.request_limit,
        max_active_requests_per_origin=config.per_origin_request_limit,
        max_pending_requests=max_pending_requests,
        max_response_body_size=config.max_response_body_size,
        max_idle_connections_per_host=idle_connection_limit,
    )
