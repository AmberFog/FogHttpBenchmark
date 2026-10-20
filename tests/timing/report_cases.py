from collections.abc import Callable
from functools import partial

from foghttp_benchmark.creation_reports import write_creation_reports
from foghttp_benchmark.models import BenchmarkArgs, ClientCreationResult
from foghttp_benchmark.one_upstream.reports import write_one_upstream_reports
from foghttp_benchmark.proxy_connect.models import ProxyStatsDelta
from foghttp_benchmark.proxy_connect.reports import write_proxy_connect_reports
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.request_builder.reports import write_request_builder_reports
from foghttp_benchmark.resource.reporting.reports import write_resource_reports
from foghttp_benchmark.streaming.reports import write_streaming_reports
from tests.one_upstream.test_reports import one_upstream_result
from tests.proxy_connect.test_reports import proxy_connect_result
from tests.request_builder.test_reports import request_builder_result
from tests.requests.factories import run_result
from tests.resource.factories import resource_result
from tests.streaming.factories import streaming_result


def creation_result() -> ClientCreationResult:
    return ClientCreationResult(
        client="foghttp",
        mode="async",
        scenario="create-close",
        client_count=1,
        iterations=1,
        repeat=1,
        duration_s=1.0,
        operations_per_second=1.0,
        p50_ms=1.0,
        p90_ms=1.0,
        p95_ms=1.0,
        p99_ms=1.0,
        min_ms=1.0,
        max_ms=1.0,
        close_p50_ms=0.5,
        close_p95_ms=0.5,
        errors=0,
        error_types={},
        peak_rss_delta_mb=1.0,
        end_rss_delta_mb=0.0,
        peak_threads_delta=0,
        end_threads_delta=0,
        peak_fds_delta=0,
        end_fds_delta=0,
    )


REPORT_CASES: list[tuple[str, str, Callable[[BenchmarkArgs], None]]] = [
    (
        suite,
        "requests-load-only-v2",
        partial(
            write_reports,
            [run_result(repeat=1, errors=0, warmup_errors=0, error_types={}, warmup_error_types={})],
            {},
        ),
    )
    for suite in ("requests", "compressed-response")
] + [
    ("client-creation", "client-creation-operation-v1", partial(write_creation_reports, [creation_result()], {})),
    (
        "one-upstream",
        "one-upstream-load-only-v2",
        partial(
            write_one_upstream_reports,
            [one_upstream_result(case="direct-get", profile="direct", ok_requests_per_second=1.0)],
            {},
        ),
    ),
    (
        "proxy-connect",
        "proxy-connect-load-only-v2",
        partial(
            write_proxy_connect_reports,
            [
                proxy_connect_result(
                    case="direct-https",
                    config="direct",
                    ok_requests_per_second=1.0,
                    measured_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
                    total_proxy=ProxyStatsDelta(0, 0, 0, 0, 0),
                ),
            ],
            {},
            proxy_url="http://127.0.0.1:1",
        ),
    ),
    (
        "request-builder",
        "request-builder-load-only-v1",
        partial(
            write_request_builder_reports,
            [request_builder_result(case="absolute-url", group="url", profile="direct", operations_per_second=1.0)],
            {},
        ),
    ),
    (
        "resource-backpressure",
        "resource-backpressure-load-only-v2",
        partial(write_resource_reports, [resource_result()], {}),
    ),
    ("response-streaming", "load-only-v2", partial(write_streaming_reports, [streaming_result()], {})),
]
