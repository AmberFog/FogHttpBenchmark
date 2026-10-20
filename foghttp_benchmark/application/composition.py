__all__ = ("SuiteDefinition", "get_suite", "run_benchmark_suite")

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from foghttp_benchmark import request_suite
from foghttp_benchmark.compressed_response import suite as compressed_response
from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.creation import suite as creation
from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.one_upstream import suite as one_upstream
from foghttp_benchmark.progress import ProgressReporter
from foghttp_benchmark.proxy_connect import suite as proxy_connect
from foghttp_benchmark.report_finalization import MergedReportFinalizer, preserve_merged_report
from foghttp_benchmark.request_builder import suite as request_builder
from foghttp_benchmark.resource import suite as resource
from foghttp_benchmark.streaming import suite as streaming
from foghttp_benchmark.suite_selection import no_scenarios, scenario_names, select_default_clients


class SuiteRunner(Protocol):
    async def __call__(self, args: BenchmarkArgs, *, progress: ProgressReporter | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class SuiteDefinition:
    run: SuiteRunner
    select_clients: Callable[[BenchmarkArgs], ClientIsolationSelection]
    isolation_scenarios: Callable[[BenchmarkArgs], list[str]]
    finalize_report: MergedReportFinalizer


SUITES: dict[str, SuiteDefinition] = {
    REQUESTS_SUITE: SuiteDefinition(
        request_suite.run_request_suite,
        select_default_clients,
        scenario_names,
        preserve_merged_report,
    ),
    CLIENT_CREATION_SUITE: SuiteDefinition(
        creation.run_client_creation_suite,
        select_default_clients,
        no_scenarios,
        preserve_merged_report,
    ),
    RESOURCE_BACKPRESSURE_SUITE: SuiteDefinition(
        resource.run_resource_backpressure_suite,
        resource.select_resource_clients,
        scenario_names,
        preserve_merged_report,
    ),
    COMPRESSED_RESPONSE_SUITE: SuiteDefinition(
        compressed_response.run_compressed_response_suite,
        select_default_clients,
        scenario_names,
        preserve_merged_report,
    ),
    ONE_UPSTREAM_SUITE: SuiteDefinition(
        one_upstream.run_one_upstream_suite,
        one_upstream.select_clients,
        scenario_names,
        preserve_merged_report,
    ),
    REQUEST_BUILDER_SUITE: SuiteDefinition(
        request_builder.run_request_builder_suite,
        request_builder.select_clients,
        scenario_names,
        preserve_merged_report,
    ),
    RESPONSE_STREAMING_SUITE: SuiteDefinition(
        streaming.run_response_streaming_suite,
        streaming.select_clients,
        scenario_names,
        streaming.finalize_merged_report,
    ),
    PROXY_CONNECT_SUITE: SuiteDefinition(
        proxy_connect.run_proxy_connect_suite,
        proxy_connect.select_clients,
        scenario_names,
        proxy_connect.finalize_merged_report,
    ),
}


def get_suite(name: str) -> SuiteDefinition:
    try:
        return SUITES[name]
    except KeyError as exc:
        msg = f"unknown benchmark suite: {name}"
        raise ValueError(msg) from exc


async def run_benchmark_suite(args: BenchmarkArgs, *, progress: ProgressReporter | None = None) -> None:
    await get_suite(args.suite).run(args, progress=progress)
