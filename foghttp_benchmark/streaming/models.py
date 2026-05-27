__all__ = (
    "AsyncStreamingAdapter",
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
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from foghttp_benchmark.models import ClientStats


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


class AsyncStreamingAdapter(Protocol):
    async def stream(self, case: StreamingCase, url: str) -> StreamingOutcome: ...

    async def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


class SyncStreamingAdapter(Protocol):
    def stream(self, case: StreamingCase, url: str) -> StreamingOutcome: ...

    def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


StreamingClientFactory: TypeAlias = Callable[
    [StreamingClientConfig],
    AsyncStreamingAdapter | SyncStreamingAdapter,
]


@dataclass(frozen=True, slots=True)
class StreamingClientSpec:
    name: str
    mode: str
    factory: StreamingClientFactory


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
    rss_mb_max: float
    threads_max: int
    fds_max: int
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
