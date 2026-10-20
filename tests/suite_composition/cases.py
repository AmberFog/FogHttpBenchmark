from dataclasses import dataclass
from types import ModuleType

from foghttp_benchmark import request_suite
from foghttp_benchmark.compressed_response import suite as compressed_suite
from foghttp_benchmark.creation import suite as creation_suite
from foghttp_benchmark.one_upstream import suite as one_upstream_suite
from foghttp_benchmark.proxy_connect import suite as proxy_suite
from foghttp_benchmark.request_builder import suite as builder_suite
from foghttp_benchmark.resource import suite as resource_suite
from foghttp_benchmark.streaming import suite as streaming_suite


@dataclass(frozen=True)
class SuiteCase:
    name: str
    module: ModuleType
    runner: str
    work: str
    writer: str
    scenarios: str
    servers: tuple[str, ...] = ("http",)
    registry: str | None = None


SUITES = (
    SuiteCase("requests", request_suite, "run_request_suite", "run_once", "write_reports", "bytes-64k,json-small"),
    SuiteCase(
        "client-creation",
        creation_suite,
        "run_client_creation_suite",
        "run_client_creation_benchmarks",
        "write_creation_reports",
        "json-small",
    ),
    SuiteCase(
        "resource-backpressure",
        resource_suite,
        "run_resource_backpressure_suite",
        "run_resource_backpressure_benchmarks",
        "write_resource_reports",
        "per-origin-isolation,active-limit-serial",
        servers=("http", "secondary"),
    ),
    SuiteCase(
        "compressed-response",
        compressed_suite,
        "run_compressed_response_suite",
        "run_once",
        "write_reports",
        "deflate-64k,gzip-64k",
    ),
    SuiteCase(
        "one-upstream",
        one_upstream_suite,
        "run_one_upstream_suite",
        "run_one_upstream_benchmarks",
        "write_one_upstream_reports",
        "base-url-get,direct-get",
        registry="available_one_upstream_clients",
    ),
    SuiteCase(
        "request-builder",
        builder_suite,
        "run_request_builder_suite",
        "run_request_builder_benchmarks",
        "write_request_builder_reports",
        "send-prepared-get,absolute-url",
        registry="available_request_builder_clients",
    ),
    SuiteCase(
        "response-streaming",
        streaming_suite,
        "run_response_streaming_suite",
        "run_response_streaming_benchmarks",
        "write_streaming_reports",
        "stream-1m,stream-64k",
        registry="available_streaming_clients",
    ),
    SuiteCase(
        "proxy-connect",
        proxy_suite,
        "run_proxy_connect_suite",
        "run_proxy_connect_benchmarks",
        "write_proxy_connect_reports",
        "proxy-connect,direct-http",
        servers=("http", "tls", "proxy"),
        registry="available_proxy_connect_clients",
    ),
)
