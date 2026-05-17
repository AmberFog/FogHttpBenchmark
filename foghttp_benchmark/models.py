__all__ = (
    "BenchmarkArgs",
    "ClientConfig",
    "ClientCreationResult",
    "ClientFactory",
    "ClientSpec",
    "ClientStatKey",
    "ClientStats",
    "JsonObject",
    "LoadResult",
    "ResourceBackpressureResult",
    "ResponseOutcome",
    "RunResult",
    "Scenario",
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias


if TYPE_CHECKING:
    from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter


@dataclass(frozen=True)
class BenchmarkArgs:
    suite: str
    clients: str
    modes: str
    concurrency: str
    requests: int
    warmup: int
    repeats: int
    max_redirects: int
    seed: int
    no_shuffle: bool
    output_dir: str
    scenarios: str
    iterations: int
    client_counts: str


@dataclass(frozen=True)
class ClientConfig:
    concurrency: int
    request_limit: int
    follow_redirects: bool
    max_redirects: int
    max_pending_requests: int | None = None
    per_origin_request_limit: int | None = None
    max_response_body_size: int | None = None
    idle_connection_limit: int | None = None
    runtime_workers: int | None = None
    pool_timeout_s: float = 5.0
    total_timeout_s: float = 30.0


ClientFactory: TypeAlias = Callable[[ClientConfig], "AsyncClientAdapter | SyncClientAdapter"]
ClientStatKey: TypeAlias = Literal[
    "active_requests",
    "pending_requests",
    "total_requests",
    "failed_requests",
    "pool_acquire_timeouts",
]
ClientStats: TypeAlias = dict[ClientStatKey, int]
JsonObject: TypeAlias = dict[str, object]


@dataclass(frozen=True)
class ClientSpec:
    name: str
    mode: str
    factory: ClientFactory


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    path: str
    body: bytes | None = None
    json_body: JsonObject | None = None
    expected_status: int = 200
    expected_json_keys: tuple[str, ...] = ()
    expected_content_length: int | None = None
    expected_redirects: int | None = None
    expected_final_path: str | None = None
    follow_redirects: bool = False
    request_limit: int | None = None
    description: str = ""


@dataclass(frozen=True)
class ResponseOutcome:
    status_code: int
    json_ok: bool = True
    content_length: int | None = None
    history_count: int | None = None
    final_url: str | None = None


@dataclass(frozen=True)
class LoadResult:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass
class RunResult:
    client: str
    mode: str
    scenario: str
    concurrency: int
    request_limit: int
    requests: int
    repeat: int
    duration_s: float
    requests_per_second: float
    ok_requests_per_second: float
    ok_requests: int
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    errors: int
    warmup_errors: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    process_cpu_s: float
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    client_stats: ClientStats | None


@dataclass
class ClientCreationResult:
    client: str
    mode: str
    scenario: str
    client_count: int
    iterations: int
    repeat: int
    duration_s: float
    operations_per_second: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    close_p50_ms: float | None
    close_p95_ms: float | None
    errors: int
    error_types: dict[str, int]
    peak_rss_delta_mb: float | None
    end_rss_delta_mb: float | None
    peak_threads_delta: int | None
    end_threads_delta: int | None
    peak_fds_delta: int | None
    end_fds_delta: int | None


@dataclass
class ResourceBackpressureResult:
    client: str
    mode: str
    scenario: str
    concurrency: int
    request_limit: int
    per_origin_request_limit: int | None
    max_pending_requests: int
    max_response_body_size: int | None
    pool_timeout_s: float
    requests: int
    warmup: int
    repeat: int
    duration_s: float
    ok_requests: int
    errors: int
    warmup_errors: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    p50_ms: float
    p95_ms: float
    p99_ms: float
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    peak_active_requests: int | None
    peak_pending_requests: int | None
    client_stats: ClientStats | None
    recovery_ok: bool | None
    recovery_error: str | None
