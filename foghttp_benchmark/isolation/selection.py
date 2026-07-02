__all__ = ("select_clients_for_isolation",)

from collections.abc import Callable, Iterable
from typing import Protocol

from foghttp_benchmark.clients import available_clients
from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.one_upstream import available_one_upstream_clients
from foghttp_benchmark.proxy_connect import available_proxy_connect_clients
from foghttp_benchmark.request_builder import available_request_builder_clients
from foghttp_benchmark.streaming import available_streaming_clients


class NamedClientSpec(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def mode(self) -> str: ...


ClientSelector = Callable[[list[str], list[str]], ClientIsolationSelection]


def select_clients_for_isolation(args: BenchmarkArgs) -> ClientIsolationSelection:
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    selector = client_selector(args.suite)
    if selector is not None:
        return selector(requested_clients, requested_modes)
    return ClientIsolationSelection([], {})


def client_selector(suite: str) -> ClientSelector | None:
    selectors: dict[str, ClientSelector] = {
        ONE_UPSTREAM_SUITE: select_one_upstream_clients,
        REQUEST_BUILDER_SUITE: select_request_builder_clients,
        RESPONSE_STREAMING_SUITE: select_streaming_clients,
        PROXY_CONNECT_SUITE: select_proxy_connect_clients,
        REQUESTS_SUITE: select_default_clients,
        CLIENT_CREATION_SUITE: select_default_clients,
        COMPRESSED_RESPONSE_SUITE: select_default_clients,
        RESOURCE_BACKPRESSURE_SUITE: select_resource_clients,
    }
    return selectors.get(suite)


def select_one_upstream_clients(requested_clients: list[str], requested_modes: list[str]) -> ClientIsolationSelection:
    clients, skipped = available_one_upstream_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(client_names(requested_clients, clients), skipped)


def select_request_builder_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> ClientIsolationSelection:
    clients, skipped = available_request_builder_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(client_names(requested_clients, clients), skipped)


def select_streaming_clients(requested_clients: list[str], requested_modes: list[str]) -> ClientIsolationSelection:
    clients, skipped = available_streaming_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(client_names(requested_clients, clients), skipped)


def select_proxy_connect_clients(requested_clients: list[str], requested_modes: list[str]) -> ClientIsolationSelection:
    clients, skipped = available_proxy_connect_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(client_names(requested_clients, clients), skipped)


def select_default_clients(requested_clients: list[str], requested_modes: list[str]) -> ClientIsolationSelection:
    clients, skipped = available_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(client_names(requested_clients, clients), skipped)


def select_resource_clients(requested_clients: list[str], requested_modes: list[str]) -> ClientIsolationSelection:
    clients, skipped = available_clients(requested_clients, requested_modes)
    return ClientIsolationSelection(
        client_names(requested_clients, resource_clients(clients)),
        {**skipped, **resource_skipped(clients)},
    )


def resource_clients(clients: Iterable[NamedClientSpec]) -> list[NamedClientSpec]:
    return [client for client in clients if client.name == "foghttp"]


def resource_skipped(clients: Iterable[NamedClientSpec]) -> dict[str, str]:
    skipped: dict[str, str] = {}
    for client in clients:
        if client.name != "foghttp":
            skipped[f"{client.mode}:{client.name}"] = "resource-backpressure suite requires FogHTTP stats"
    return skipped


def client_names(requested_clients: list[str], clients: Iterable[NamedClientSpec]) -> list[str]:
    available = {client.name for client in clients}
    return [name for name in requested_clients if name in available]


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
