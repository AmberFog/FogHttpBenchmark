__all__ = (
    "AsyncRequestBuilderAdapter",
    "BodyKind",
    "BuilderKind",
    "ParamsKind",
    "RequestBuilderAggregateRow",
    "RequestBuilderCase",
    "RequestBuilderClientConfig",
    "RequestBuilderClientFactory",
    "RequestBuilderClientSpec",
    "RequestBuilderResult",
    "RequestBuilderStats",
    "SyncRequestBuilderAdapter",
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias


BodyKind: TypeAlias = Literal["none", "json", "bytes"]
BuilderKind: TypeAlias = Literal["build", "send-prepared"]
ParamsKind: TypeAlias = Literal["none", "scalar", "repeated", "raw", "many"]
QueryItems: TypeAlias = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RequestBuilderCase:
    name: str
    group: str
    kind: BuilderKind
    profile: str
    method: str
    path: str
    uses_base_url: bool
    default_headers: bool = False
    default_params: bool = False
    request_headers: bool = False
    params_kind: ParamsKind = "none"
    body_kind: BodyKind = "none"
    description: str = ""


@dataclass(frozen=True, slots=True)
class RequestBuilderClientConfig:
    base_url: str | None
    headers: dict[str, str] | None
    params: QueryItems | None
    request_limit: int = 1
    pool_timeout_s: float = 5.0


class AsyncRequestBuilderAdapter(Protocol):
    def build(self, case: RequestBuilderCase, base_url: str) -> object: ...

    async def send(self, request: object) -> int: ...

    async def close(self) -> None: ...


class SyncRequestBuilderAdapter(Protocol):
    def build(self, case: RequestBuilderCase, base_url: str) -> object: ...

    def send(self, request: object) -> int: ...

    def close(self) -> None: ...


RequestBuilderClientFactory: TypeAlias = Callable[
    [RequestBuilderClientConfig],
    AsyncRequestBuilderAdapter | SyncRequestBuilderAdapter,
]


@dataclass(frozen=True, slots=True)
class RequestBuilderClientSpec:
    name: str
    mode: str
    factory: RequestBuilderClientFactory


@dataclass(frozen=True, slots=True)
class RequestBuilderStats:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass
class RequestBuilderResult:
    client: str
    mode: str
    case: str
    group: str
    kind: str
    profile: str
    iterations: int
    repeat: int
    duration_s: float
    operations_per_second: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    errors: int
    error_types: dict[str, int]
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None


@dataclass(frozen=True, slots=True)
class RequestBuilderAggregateRow:
    mode: str
    client: str
    case: str
    group: str
    kind: str
    profile: str
    iterations: int
    repeats: int
    duration_ms_median: float
    ops_s_median: float
    ops_s_cv_percent: float
    baseline_ratio: float | None
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    rss_mb_max: float
    threads_max: int
    fds_max: int
    errors_total: int
    error_types: dict[str, int]
