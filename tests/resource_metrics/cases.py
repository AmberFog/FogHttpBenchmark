from dataclasses import dataclass
from functools import partial
from typing import TypeAlias, cast

from foghttp_benchmark.models import ClientCreationResult, ResourceBackpressureResult, RunResult
from foghttp_benchmark.one_upstream.models import OneUpstreamResult
from foghttp_benchmark.proxy_connect.models import ProxyConnectResult
from foghttp_benchmark.request_builder.models import RequestBuilderResult
from foghttp_benchmark.streaming.models import StreamingResult
from tests.timing.report_cases import REPORT_CASES


ResourceResult: TypeAlias = (
    RunResult
    | ClientCreationResult
    | ResourceBackpressureResult
    | OneUpstreamResult
    | ProxyConnectResult
    | RequestBuilderResult
    | StreamingResult
)


@dataclass(frozen=True, slots=True)
class ResourceField:
    source: str
    aggregate: str
    client_stat: bool = False


@dataclass(frozen=True, slots=True)
class ResourceReportCase:
    suite: str
    writer: partial[None]
    metrics: tuple[ResourceField, ...]


PROCESS_FIELDS = (
    ResourceField("peak_rss_mb", "rss_mb_max"),
    ResourceField("peak_threads", "threads_max"),
    ResourceField("peak_fds", "fds_max"),
)
CREATION_FIELDS = tuple(
    ResourceField(f"{phase}_{metric}_delta{unit}", f"{phase}_{metric}_delta{unit}_max")
    for phase in ("peak", "end")
    for metric, unit in (("rss", "_mb"), ("threads", ""), ("fds", ""))
)
RESOURCE_FIELDS = (
    ResourceField("peak_active_requests", "peak_active_requests_max"),
    ResourceField("peak_pending_requests", "peak_pending_requests_max"),
    ResourceField("peak_buffered_response_bytes", "peak_buffered_response_bytes_max"),
    ResourceField("failed_requests", "final_failed_requests_max", client_stat=True),
    ResourceField("pool_acquire_timeouts", "final_pool_timeouts_max", client_stat=True),
    ResourceField("buffered_response_bytes", "final_buffered_response_bytes_max", client_stat=True),
    ResourceField(
        "buffered_response_budget_rejections",
        "final_buffered_response_budget_rejections_max",
        client_stat=True,
    ),
)
STREAMING_FIELDS = tuple(
    ResourceField(metric, f"final_{metric}_max", client_stat=True)
    for metric in (
        "active_requests",
        "response_body_closed",
        "response_body_reuse_eligible",
        "response_body_aborted",
        "connections_opened",
        "connections_reused",
        "connections_closed",
        "connections_aborted",
        "idle_connections",
    )
)
PROXY_FIELDS = tuple(
    ResourceField(metric, f"final_{metric}_max", client_stat=True)
    for metric in ("connections_opened", "connections_reused", "connections_closed", "connections_aborted")
)
EXTRA_FIELDS = {
    "resource-backpressure": RESOURCE_FIELDS,
    "response-streaming": STREAMING_FIELDS,
    "proxy-connect": PROXY_FIELDS,
}
RESOURCE_REPORT_CASES = [
    ResourceReportCase(
        suite,
        cast("partial[None]", writer),
        CREATION_FIELDS if suite == "client-creation" else PROCESS_FIELDS + EXTRA_FIELDS.get(suite, ()),
    )
    for suite, _scope, writer in REPORT_CASES
]
OBSERVATION_CASES = [
    (None, None),
    (None, 7),
    (0, 0),
    (3, 7),
]
OBSERVATION_IDS = ["unavailable", "partial", "measured-zero", "positive"]
RESOURCE_SCHEMA_VERSION = 2
EXACT_LARGE_RESOURCE_COUNT = 2**60 + 1
