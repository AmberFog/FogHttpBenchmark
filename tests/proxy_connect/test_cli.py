from foghttp_benchmark.cli import (
    proxy_connect_concurrency_levels,
    proxy_connect_report_args,
    proxy_connect_requests,
    proxy_connect_scenario_names,
    proxy_connect_warmup,
)
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_PROXY_CONNECT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_REQUESTS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_PROXY_CONNECT_WARMUP,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs


def test_proxy_connect_report_args_record_effective_defaults() -> None:
    args = BenchmarkArgs(
        suite=PROXY_CONNECT_SUITE,
        clients=DEFAULT_CLIENTS,
        modes=DEFAULT_MODES,
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir="results",
        scenarios=DEFAULT_SCENARIOS,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
    requested_cases = proxy_connect_scenario_names(args.scenarios)
    concurrency_levels = proxy_connect_concurrency_levels(args.concurrency)

    report_args = proxy_connect_report_args(
        args,
        requested_cases=requested_cases,
        requests=proxy_connect_requests(args.requests),
        warmup=proxy_connect_warmup(args.warmup),
        concurrency_levels=concurrency_levels,
    )

    assert report_args.requests == DEFAULT_PROXY_CONNECT_REQUESTS
    assert report_args.warmup == DEFAULT_PROXY_CONNECT_WARMUP
    assert report_args.scenarios == DEFAULT_PROXY_CONNECT_SCENARIOS
    assert report_args.concurrency == DEFAULT_PROXY_CONNECT_CONCURRENCY
