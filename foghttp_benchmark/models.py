__all__ = (
    "BenchmarkArgs",
    "ClientConfig",
    "ClientCreationResult",
    "ClientFactory",
    "ClientSpec",
    "LoadResult",
    "ResponseOutcome",
    "RunResult",
    "Scenario",
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias


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
    max_connections: int
    follow_redirects: bool
    max_redirects: int


ClientFactory: TypeAlias = Callable[[ClientConfig], "AsyncClientAdapter | SyncClientAdapter"]


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
    json_body: dict[str, Any] | None = None
    expected_status: int = 200
    expected_json_keys: tuple[str, ...] = ()
    expected_content_length: int | None = None
    expected_redirects: int | None = None
    expected_final_path: str | None = None
    follow_redirects: bool = False
    max_connections: int | None = None
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
    max_connections: int
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
    client_stats: dict[str, Any] | None


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
