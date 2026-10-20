from types import ModuleType

import pytest

from foghttp_benchmark import request_suite
from foghttp_benchmark.compressed_response import suite as compressed_suite
from foghttp_benchmark.creation import suite as creation_suite
from foghttp_benchmark.one_upstream import suite as one_upstream_suite
from foghttp_benchmark.proxy_connect import suite as proxy_suite
from foghttp_benchmark.request_builder import suite as request_builder_suite
from foghttp_benchmark.resource import suite as resource_suite
from foghttp_benchmark.streaming import suite as streaming_suite
from tests.cli_defaults.support import fake_benchmark_server, fake_proxy_server, fake_tls_server


SUITE_ROUTES = {
    "requests": (request_suite, "run_request_suite"),
    "client-creation": (creation_suite, "run_client_creation_suite"),
    "resource-backpressure": (resource_suite, "run_resource_backpressure_suite"),
    "compressed-response": (compressed_suite, "run_compressed_response_suite"),
    "one-upstream": (one_upstream_suite, "run_one_upstream_suite"),
    "request-builder": (request_builder_suite, "run_request_builder_suite"),
    "response-streaming": (streaming_suite, "run_response_streaming_suite"),
    "proxy-connect": (proxy_suite, "run_proxy_connect_suite"),
}
COMMON_CLIENT_SUITES = {"requests", "client-creation", "resource-backpressure", "compressed-response"}
LEAF_WORK = {
    "requests": ("build_plan", "write_reports", "json-small"),
    "client-creation": ("run_client_creation_benchmarks", "write_creation_reports", "json-small"),
    "resource-backpressure": ("run_resource_backpressure_benchmarks", "write_resource_reports", "active-limit-serial"),
    "compressed-response": ("build_plan", "write_reports", "gzip-64k"),
    "one-upstream": ("run_one_upstream_benchmarks", "write_one_upstream_reports", "direct-get"),
    "request-builder": ("run_request_builder_benchmarks", "write_request_builder_reports", "send-prepared-get"),
    "response-streaming": ("run_response_streaming_benchmarks", "write_streaming_reports", "stream-1m"),
    "proxy-connect": ("run_proxy_connect_benchmarks", "write_proxy_connect_reports", "proxy-connect"),
}
SPECIALIZED_REGISTRIES = {
    "one-upstream": "available_one_upstream_clients",
    "request-builder": "available_request_builder_clients",
    "response-streaming": "available_streaming_clients",
    "proxy-connect": "available_proxy_connect_clients",
}


def patch_suite_servers(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    monkeypatch.setattr(module, "benchmark_server", fake_benchmark_server)
    if module is proxy_suite:
        monkeypatch.setattr(module, "benchmark_tls_server", fake_tls_server)
        monkeypatch.setattr(module, "http_proxy_server", fake_proxy_server)
