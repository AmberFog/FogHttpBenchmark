__all__ = (
    "AsyncStreamingAdapter",
    "AsyncStreamingClientFactory",
    "AsyncStreamingClientSpec",
    "StreamConsumeMode",
    "StreamReadMode",
    "StreamingAggregateRow",
    "StreamingCase",
    "StreamingClientConfig",
    "StreamingClientFactory",
    "StreamingClientSpec",
    "StreamingLoadResult",
    "StreamingOutcome",
    "StreamingResult",
    "SyncStreamingAdapter",
    "SyncStreamingClientFactory",
    "SyncStreamingClientSpec",
)

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.resource_metrics import ResourceCoverage


StreamConsumeMode: TypeAlias = Literal["all", "first-chunk", "first-line"]
StreamReadMode: TypeAlias = Literal["bytes", "text", "lines"]


@dataclass(frozen=True, slots=True)
class StreamingCase:
    name: str
    path: str
    size_bytes: int
    chunk_size_bytes: int
    delay_ms: int
    read: StreamReadMode = "bytes"
    consume: StreamConsumeMode = "all"
    expected_lines: int | None = None
    description: str = ""
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StreamingClientConfig:
    concurrency: int
    request_limit: int
    pool_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    total_timeout_s: float = 30.0


@dataclass(frozen=True, slots=True)
class StreamingOutcome:
    status_code: int
    bytes_read: int
    chunks_read: int
    first_chunk_ms: float | None
    text_chars_read: int = 0
    lines_read: int = 0
    body_sha256: str | None = None
    eof_received: bool = False


class AsyncStreamingAdapter(Protocol):
    @property
    def mode(self) -> Literal["async"]: ...

    async def stream(self, case: StreamingCase, url: str) -> StreamingOutcome: ...

    async def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


class SyncStreamingAdapter(Protocol):
    @property
    def mode(self) -> Literal["sync"]: ...

    def stream(self, case: StreamingCase, url: str) -> StreamingOutcome: ...

    def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


AsyncStreamingClientFactory: TypeAlias = Callable[[StreamingClientConfig], AsyncStreamingAdapter]
SyncStreamingClientFactory: TypeAlias = Callable[[StreamingClientConfig], SyncStreamingAdapter]
StreamingClientFactory: TypeAlias = AsyncStreamingClientFactory | SyncStreamingClientFactory


@dataclass(frozen=True, slots=True)
class AsyncStreamingClientSpec:
    name: str
    factory: AsyncStreamingClientFactory
    mode: Literal["async"] = field(default=ASYNC_MODE, init=False)


@dataclass(frozen=True, slots=True)
class SyncStreamingClientSpec:
    name: str
    factory: SyncStreamingClientFactory
    mode: Literal["sync"] = field(default=SYNC_MODE, init=False)


StreamingClientSpec: TypeAlias = AsyncStreamingClientSpec | SyncStreamingClientSpec


@dataclass(frozen=True, slots=True)
class StreamingLoadResult:
    latencies_ms: list[float]
    first_chunk_latencies_ms: list[float]
    bytes_read: int
    chunks_read: int
    text_chars_read: int
    lines_read: int
    errors: int
    error_types: dict[str, int]
    verified_eof_bytes: int = 0
    verified_eof_chunks: int = 0


@dataclass
class StreamingResult:
    client: str
    mode: str
    case: str
    read: str
    consume: str
    concurrency: int
    request_limit: int
    requests: int
    repeat: int
    duration_s: float
    streams_per_second: float
    ok_streams_per_second: float
    ok_streams: int
    bytes_read_total: int
    mb_per_second: float
    chunks_read_total: int
    text_chars_read_total: int
    lines_read_total: int
    lines_per_second: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    first_chunk_p50_ms: float | None
    first_chunk_p95_ms: float | None
    errors: int
    warmup_errors: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    client_stats: ClientStats | None
    verified_eof_bytes_total: int = 0
    verified_eof_chunks_total: int = 0
    throughput_scope: str = "verified-eof-v2"
    timing_scope: str = "load-only-v2"


@dataclass(frozen=True, slots=True)
class StreamingAggregateRow:
    mode: str
    client: str
    case: str
    read: str
    consume: str
    concurrency: int
    request_limit: int
    requests: int
    repeats: int
    ok_streams_total: int
    errors_total: int
    warmup_errors_total: int
    warmup_error_types: dict[str, int]
    error_rate_percent: float
    ok_streams_s_median: float
    streams_s_median: float
    streams_s_cv_percent: float
    mb_s_median: float
    lines_s_median: float
    text_chars_read_total: int
    lines_read_total: int
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    first_chunk_p50_ms_median: float | None
    first_chunk_p95_ms_median: float | None
    rss_mb_max: float | None
    threads_max: int | None
    fds_max: int | None
    final_active_requests_max: int | None
    final_response_body_closed_max: int | None
    final_response_body_reuse_eligible_max: int | None
    final_response_body_aborted_max: int | None
    final_connections_opened_max: int | None
    final_connections_reused_max: int | None
    final_connections_closed_max: int | None
    final_connections_aborted_max: int | None
    final_idle_connections_max: int | None
    error_types: dict[str, int]
    bytes_read_total: int = 0
    chunks_read_total: int = 0
    verified_eof_bytes_total: int = 0
    verified_eof_chunks_total: int = 0
    throughput_scope: str = "verified-eof-v2"
    timing_scope: str = "load-only-v2"
    resource_coverage: ResourceCoverage = field(default_factory=dict)
