__all__ = (
    "AsyncRequestBuilderAdapter",
    "AsyncRequestBuilderClientFactory",
    "AsyncRequestBuilderClientSpec",
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
    "SyncRequestBuilderClientFactory",
    "SyncRequestBuilderClientSpec",
)

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE
from foghttp_benchmark.resource_metrics import ResourceCoverage


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
    @property
    def mode(self) -> Literal["async"]: ...

    def build(self, case: RequestBuilderCase, base_url: str) -> object: ...

    async def send(self, request: object) -> int: ...

    async def close(self) -> None: ...


class SyncRequestBuilderAdapter(Protocol):
    @property
    def mode(self) -> Literal["sync"]: ...

    def build(self, case: RequestBuilderCase, base_url: str) -> object: ...

    def send(self, request: object) -> int: ...

    def close(self) -> None: ...


AsyncRequestBuilderClientFactory: TypeAlias = Callable[[RequestBuilderClientConfig], AsyncRequestBuilderAdapter]
SyncRequestBuilderClientFactory: TypeAlias = Callable[[RequestBuilderClientConfig], SyncRequestBuilderAdapter]
RequestBuilderClientFactory: TypeAlias = AsyncRequestBuilderClientFactory | SyncRequestBuilderClientFactory


@dataclass(frozen=True, slots=True)
class AsyncRequestBuilderClientSpec:
    name: str
    factory: AsyncRequestBuilderClientFactory
    mode: Literal["async"] = field(default=ASYNC_MODE, init=False)


@dataclass(frozen=True, slots=True)
class SyncRequestBuilderClientSpec:
    name: str
    factory: SyncRequestBuilderClientFactory
    mode: Literal["sync"] = field(default=SYNC_MODE, init=False)


RequestBuilderClientSpec: TypeAlias = AsyncRequestBuilderClientSpec | SyncRequestBuilderClientSpec


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
    rss_mb_max: float | None
    threads_max: int | None
    fds_max: int | None
    errors_total: int
    error_types: dict[str, int]
    resource_coverage: ResourceCoverage = field(default_factory=dict)
