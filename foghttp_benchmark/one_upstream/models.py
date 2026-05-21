__all__ = (
    "AsyncOneUpstreamAdapter",
    "BodyKind",
    "OneUpstreamAggregateRow",
    "OneUpstreamCase",
    "OneUpstreamClientConfig",
    "OneUpstreamClientFactory",
    "OneUpstreamClientSpec",
    "OneUpstreamResult",
    "OneUpstreamStats",
    "ProfileKind",
    "SyncOneUpstreamAdapter",
)

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias


BodyKind: TypeAlias = Literal["none", "json", "form"]
ProfileKind: TypeAlias = Literal["direct", "base-url", "defaults", "prepared"]
QueryItems: TypeAlias = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OneUpstreamCase:
    name: str
    group: str
    profile: ProfileKind
    method: str
    body_kind: BodyKind = "none"
    description: str = ""

    @property
    def uses_base_url(self) -> bool:
        return self.profile in {"base-url", "defaults", "prepared"}

    @property
    def uses_defaults(self) -> bool:
        return self.profile in {"defaults", "prepared"}

    @property
    def uses_prepared_request(self) -> bool:
        return self.profile == "prepared"


@dataclass(frozen=True, slots=True)
class OneUpstreamClientConfig:
    concurrency: int
    request_limit: int
    base_url: str | None
    headers: dict[str, str] | None
    params: QueryItems | None
    pool_timeout_s: float = 5.0
    total_timeout_s: float = 30.0


class AsyncOneUpstreamAdapter(Protocol):
    async def request(self, case: OneUpstreamCase, base_url: str) -> bool: ...

    async def close(self) -> None: ...


class SyncOneUpstreamAdapter(Protocol):
    def request(self, case: OneUpstreamCase, base_url: str) -> bool: ...

    def close(self) -> None: ...


OneUpstreamClientFactory: TypeAlias = Callable[
    [OneUpstreamClientConfig],
    AsyncOneUpstreamAdapter | SyncOneUpstreamAdapter,
]


@dataclass(frozen=True, slots=True)
class OneUpstreamClientSpec:
    name: str
    mode: str
    factory: OneUpstreamClientFactory


@dataclass(frozen=True, slots=True)
class OneUpstreamStats:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass
class OneUpstreamResult:
    client: str
    mode: str
    case: str
    group: str
    profile: str
    concurrency: int
    request_limit: int
    requests: int
    repeat: int
    duration_s: float
    requests_per_second: float
    ok_requests_per_second: float
    ok_requests: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    errors: int
    warmup_errors: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None


@dataclass(frozen=True, slots=True)
class OneUpstreamAggregateRow:
    mode: str
    client: str
    case: str
    group: str
    profile: str
    concurrency: int
    request_limit: int
    requests: int
    repeats: int
    ok_requests_total: int
    errors_total: int
    warmup_errors_total: int
    error_rate_percent: float
    ok_req_s_median: float
    req_s_median: float
    req_s_cv_percent: float
    baseline_ratio: float | None
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    rss_mb_max: float
    threads_max: int
    fds_max: int
    error_types: dict[str, int]


def query_items(items: Sequence[tuple[str, str]]) -> QueryItems:
    return tuple(items)
