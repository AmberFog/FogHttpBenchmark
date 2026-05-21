__all__ = (
    "CLIENT_STAT_KEYS",
    "StatsProvider",
    "client_stats_from_raw",
    "json_has_keys",
    "request_kwargs",
    "response_content",
    "response_outcome",
    "stats_from_client",
)

from collections.abc import Mapping
from dataclasses import is_dataclass
from typing import Any, Protocol

from foghttp_benchmark.models import ClientStatKey, ClientStats, JsonObject, ResponseOutcome, Scenario


CLIENT_STAT_KEYS: tuple[ClientStatKey, ...] = (
    "active_requests",
    "pending_requests",
    "peak_pending_requests",
    "total_requests",
    "failed_requests",
    "pool_acquire_attempts",
    "pool_acquire_immediate",
    "pool_acquire_waited",
    "pool_acquire_timeouts",
    "pool_acquire_wait_time_total_ns",
    "pool_acquire_wait_time_max_ns",
    "pool_acquire_wait_time_last_ns",
    "buffered_response_bytes",
    "buffered_response_budget_rejections",
)


class StatsProvider(Protocol):
    def stats(self) -> object | None: ...


def request_kwargs(scenario: Scenario, *, body_key: str) -> JsonObject:
    if scenario.json_body is not None:
        return {"json": scenario.json_body}
    if scenario.body is not None:
        return {body_key: scenario.body}
    return {}


def response_outcome(
    *,
    response: Any,
    scenario: Scenario,
    status_code: int,
    history_count: int | None = None,
    final_url: str | None = None,
) -> ResponseOutcome:
    json_ok = True
    if scenario.expected_json_keys:
        json_ok = json_has_keys(read_response_json(response), scenario.expected_json_keys)

    content_length = None
    if scenario.expected_content_length is not None:
        content = response_content(response)
        content_length = len(content) if isinstance(content, bytes | bytearray) else None

    return ResponseOutcome(
        status_code=status_code,
        json_ok=json_ok,
        content_length=content_length,
        history_count=history_count,
        final_url=final_url,
    )


def read_response_json(response: Any) -> Any:
    reader = response.json
    return reader() if callable(reader) else reader


def response_content(response: Any) -> bytes | bytearray | None:
    reader = getattr(response, "read", None)
    if callable(reader):
        content = reader()
        if isinstance(content, bytes | bytearray):
            return content

    content = getattr(response, "content", None)
    return content if isinstance(content, bytes | bytearray) else None


def json_has_keys(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and all(key in value for key in keys)


def stats_from_client(client: StatsProvider) -> ClientStats | None:
    return client_stats_from_raw(client.stats())


def client_stats_from_raw(stats: object | None) -> ClientStats | None:
    if stats is None:
        return None
    if is_dataclass(stats) and not isinstance(stats, type):
        return client_stats_from_dataclass(stats)
    if isinstance(stats, Mapping):
        return client_stats_from_mapping(stats)
    return None


def client_stats_from_dataclass(stats: object) -> ClientStats:
    return client_stats_from_mapping({key: getattr(stats, key, None) for key in CLIENT_STAT_KEYS})


def client_stats_from_mapping(stats: Mapping[object, object]) -> ClientStats:
    typed_stats: ClientStats = {}
    for key in CLIENT_STAT_KEYS:
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            typed_stats[key] = value
    return typed_stats
