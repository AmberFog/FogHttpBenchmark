from dataclasses import dataclass, field
import threading

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.models import (
    AsyncClientSpec,
    ClientConfig,
    ClientSpec,
    ClientStats,
    ResponseOutcome,
    Scenario,
    SyncClientSpec,
)


@dataclass
class ClientEvents:
    events: list[tuple[str, int]] = field(default_factory=list)
    request_failure: bool = False
    stats_failure: bool = False
    fail_create_after: int | None = None
    created: int = 0

    def record(self, name: str) -> None:
        self.events.append((name, threading.get_ident()))

    def request(self, scenario: Scenario) -> ResponseOutcome:
        self.record("request")
        if self.request_failure:
            message = "injected request failure"
            raise ValueError(message)
        return ResponseOutcome(200, content_length=scenario.expected_content_length)

    def before_create(self) -> None:
        self.record("create")
        if self.fail_create_after is not None and self.created >= self.fail_create_after:
            message = "injected factory failure"
            raise ValueError(message)
        self.created += 1

    def stats(self) -> ClientStats | None:
        self.record("stats")
        if self.stats_failure:
            message = "injected stats failure"
            raise RuntimeError(message)
        return None


class AsyncRecordedClient(AsyncClientAdapter):
    def __init__(self, events: ClientEvents) -> None:
        self.events = events

    async def request(self, scenario: Scenario, _url: str) -> ResponseOutcome:
        return self.events.request(scenario)

    async def close(self) -> None:
        self.events.record("close")

    def stats(self) -> ClientStats | None:
        return self.events.stats()


class SyncRecordedClient(SyncClientAdapter):
    def __init__(self, events: ClientEvents) -> None:
        self.events = events

    def request(self, scenario: Scenario, _url: str) -> ResponseOutcome:
        return self.events.request(scenario)

    def close(self) -> None:
        self.events.record("close")

    def stats(self) -> ClientStats | None:
        return self.events.stats()


def recorded_spec(mode: str, events: ClientEvents) -> ClientSpec:
    def make_async(_config: ClientConfig) -> AsyncRecordedClient:
        events.before_create()
        return AsyncRecordedClient(events)

    def make_sync(_config: ClientConfig) -> SyncRecordedClient:
        events.before_create()
        return SyncRecordedClient(events)

    return AsyncClientSpec("fake", make_async) if mode == "async" else SyncClientSpec("fake", make_sync)
