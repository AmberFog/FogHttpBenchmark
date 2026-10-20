__all__ = (
    "available_clients_for_suite",
    "isolation_selection",
    "no_scenarios",
    "parse_csv",
    "parse_int_csv",
    "scenario_names",
    "select_default_clients",
)

from collections.abc import Iterable
from typing import Protocol

from foghttp_benchmark.clients import available_clients
from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs, ClientSpec


class NamedClientSpec(Protocol):
    @property
    def name(self) -> str: ...


def available_clients_for_suite(args: BenchmarkArgs) -> tuple[list[ClientSpec], dict[str, str]]:
    clients, skipped = available_clients(parse_csv(args.clients), parse_csv(args.modes))
    if not clients:
        msg = f"No requested clients are available: {skipped}"
        raise ValueError(msg)
    return clients, skipped


def isolation_selection(
    args: BenchmarkArgs,
    clients: Iterable[NamedClientSpec],
    skipped: dict[str, str],
) -> ClientIsolationSelection:
    available = {client.name for client in clients}
    names = [name for name in parse_csv(args.clients) if name in available]
    return ClientIsolationSelection(names, skipped)


def select_default_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_clients(parse_csv(args.clients), parse_csv(args.modes))
    return isolation_selection(args, clients, skipped)


def scenario_names(args: BenchmarkArgs) -> list[str]:
    return parse_csv(args.scenarios)


def no_scenarios(_args: BenchmarkArgs) -> list[str]:
    return []


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    try:
        return [int(item) for item in parse_csv(value)]
    except ValueError as exc:
        msg = f"invalid integer list: {value}"
        raise ValueError(msg) from exc
