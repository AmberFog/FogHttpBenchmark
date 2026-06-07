from foghttp_benchmark.cli import (
    response_streaming_report_args,
    streaming_requests,
    streaming_scenario_names,
)
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_STREAMING_SCENARIOS,
    DEFAULT_WARMUP,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs


def test_response_streaming_report_args_record_effective_scenarios() -> None:
    args = BenchmarkArgs(
        suite=RESPONSE_STREAMING_SUITE,
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
    requested_cases = streaming_scenario_names(args.scenarios)

    report_args = response_streaming_report_args(
        args,
        requested_cases=requested_cases,
        requests=streaming_requests(args.requests),
    )

    assert report_args.requests == DEFAULT_STREAMING_REQUESTS
    assert report_args.scenarios == DEFAULT_STREAMING_SCENARIOS
