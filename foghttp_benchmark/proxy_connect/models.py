__all__ = (
    "AsyncProxyConnectAdapter",
    "ProxyConfigKind",
    "ProxyConnectAggregateRow",
    "ProxyConnectCase",
    "ProxyConnectClientConfig",
    "ProxyConnectClientFactory",
    "ProxyConnectClientSpec",
    "ProxyConnectEndpoints",
    "ProxyConnectLoadResult",
    "ProxyConnectResult",
    "ProxyConnectStats",
    "ProxyLifecycle",
    "ProxyStatsDelta",
    "ProxyTargetScheme",
    "SyncProxyConnectAdapter",
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from foghttp_benchmark.models import ClientStats


ProxyConfigKind: TypeAlias = Literal["direct", "explicit", "trust-env"]
ProxyLifecycle: TypeAlias = Literal["reused-client", "cold-client"]
ProxyTargetScheme: TypeAlias = Literal["http", "https"]


@dataclass(frozen=True, slots=True)
class ProxyConnectCase:
    name: str
    group: str
    target_scheme: ProxyTargetScheme
    config: ProxyConfigKind
    lifecycle: ProxyLifecycle = "reused-client"
    path: str = "/json-small"
    description: str = ""

    @property
    def uses_proxy(self) -> bool:
        return self.config != "direct"

    @property
    def uses_trust_env(self) -> bool:
        return self.config == "trust-env"

    @property
    def uses_connect(self) -> bool:
        return self.uses_proxy and self.target_scheme == "https"


@dataclass(frozen=True, slots=True)
class ProxyConnectEndpoints:
    http_base_url: str
    https_base_url: str
    proxy_url: str
    ca_cert_path: str


@dataclass(frozen=True, slots=True)
class ProxyConnectClientConfig:
    concurrency: int
    request_limit: int
    proxy_url: str
    ca_cert_path: str
    config: ProxyConfigKind
    lifecycle: ProxyLifecycle
    pool_timeout_s: float = 5.0
    total_timeout_s: float = 30.0


@dataclass(frozen=True, slots=True)
class ProxyConnectStats:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass(frozen=True, slots=True)
class ProxyStatsDelta:
    http_requests: int
    connect_requests: int
    proxy_authorization_headers: int
    tunnel_client_bytes: int
    tunnel_upstream_bytes: int


class AsyncProxyConnectAdapter(Protocol):
    async def request(self, case: ProxyConnectCase, url: str) -> bool: ...

    async def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


class SyncProxyConnectAdapter(Protocol):
    def request(self, case: ProxyConnectCase, url: str) -> bool: ...

    def close(self) -> None: ...

    def stats(self) -> ClientStats | None: ...


ProxyConnectClientFactory: TypeAlias = Callable[
    [ProxyConnectClientConfig],
    AsyncProxyConnectAdapter | SyncProxyConnectAdapter,
]


@dataclass(frozen=True, slots=True)
class ProxyConnectClientSpec:
    name: str
    mode: str
    factory: ProxyConnectClientFactory


@dataclass(frozen=True, slots=True)
class ProxyConnectLoadResult:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass
class ProxyConnectResult:
    client: str
    mode: str
    case: str
    group: str
    target_scheme: str
    config: str
    lifecycle: str
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
    measured_proxy: ProxyStatsDelta
    total_proxy: ProxyStatsDelta
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    client_stats: ClientStats | None


@dataclass(frozen=True, slots=True)
class ProxyConnectAggregateRow:
    mode: str
    client: str
    case: str
    group: str
    target_scheme: str
    config: str
    lifecycle: str
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
    direct_ratio: float | None
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    rss_mb_max: float
    threads_max: int
    fds_max: int
    measured_proxy_http_requests_max: int
    measured_proxy_connect_requests_max: int
    total_proxy_http_requests_max: int
    total_proxy_connect_requests_max: int
    proxy_authorization_headers_max: int
    final_connections_opened_max: int | None
    final_connections_reused_max: int | None
    final_connections_closed_max: int | None
    final_connections_aborted_max: int | None
    error_types: dict[str, int]
