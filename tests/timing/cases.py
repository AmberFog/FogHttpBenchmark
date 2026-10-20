from typing import Literal, TypeAlias

from foghttp_benchmark import runner
from foghttp_benchmark.compressed_response.suite import run_compressed_response_suite
from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.models import AsyncClientSpec, BenchmarkArgs, ResourceBackpressureResult, RunResult, Scenario
from foghttp_benchmark.one_upstream import runner as one_upstream_runner
from foghttp_benchmark.one_upstream.models import AsyncOneUpstreamClientSpec, OneUpstreamCase, OneUpstreamResult
from foghttp_benchmark.proxy_connect import runner as proxy_runner
from foghttp_benchmark.proxy_connect.cases import proxy_connect_cases
from foghttp_benchmark.proxy_connect.models import (
    AsyncProxyConnectClientSpec,
    ProxyConnectEndpoints,
    ProxyConnectResult,
)
from foghttp_benchmark.proxy_connect.proxy_server import ProxyServerStats
from foghttp_benchmark.resource import runner as resource_runner
from foghttp_benchmark.resource.scenarios import resource_cases
from tests.timing.support import TimingHarness


Suite: TypeAlias = Literal["requests", "compressed-response", "one-upstream", "proxy-connect", "resource"]
SUITES: tuple[Suite, ...] = ("requests", "compressed-response", "one-upstream", "proxy-connect", "resource")
Result: TypeAlias = RunResult | OneUpstreamResult | ProxyConnectResult | ResourceBackpressureResult
REQUESTS = 4


async def run_case(suite: Suite, harness: TimingHarness) -> Result:
    if suite == "compressed-response":
        await run_compressed_response_suite(
            BenchmarkArgs(
                suite=suite,
                clients="fake",
                modes=ASYNC_MODE,
                concurrency="1",
                requests=REQUESTS,
                warmup=1,
                repeats=1,
                max_redirects=1,
                seed=42,
                no_shuffle=True,
                output_dir="unused",
                scenarios="gzip-64k",
                iterations=1,
                client_counts="1",
            ),
        )
        return harness.results[0]
    if suite == "one-upstream":
        return await one_upstream_runner.run_one_upstream_case(
            spec=AsyncOneUpstreamClientSpec("fake", harness.client),
            base_url="http://benchmark.invalid",
            case=OneUpstreamCase("direct-get", "get", "direct", "GET"),
            concurrency=1,
            requests=REQUESTS,
            warmup=1,
            repeat=1,
        )
    if suite == "proxy-connect":
        return await proxy_runner.run_proxy_connect_case(
            spec=AsyncProxyConnectClientSpec("fake", harness.client),
            endpoints=ProxyConnectEndpoints(
                "http://benchmark.invalid",
                "https://benchmark.invalid",
                "http://proxy.invalid",
                "unused.crt",
            ),
            proxy_stats=ProxyServerStats(),
            case=proxy_connect_cases()["direct-http"],
            concurrency=1,
            requests=REQUESTS,
            warmup=1,
            repeat=1,
        )
    spec = AsyncClientSpec("fake", harness.client)
    if suite == "resource":
        return await resource_runner.run_resource_case(
            spec=spec,
            base_url="http://benchmark.invalid",
            secondary_base_url="http://secondary.invalid",
            case=resource_cases()["active-limit-serial"],
            concurrency=1,
            requests=REQUESTS,
            warmup=1,
            repeat=1,
            max_redirects=1,
        )
    return await runner.run_once(
        spec=spec,
        base_url="http://benchmark.invalid",
        scenario=Scenario("request", "GET", "/bytes"),
        concurrency=1,
        requests=REQUESTS,
        warmup=1,
        repeat=1,
    )
