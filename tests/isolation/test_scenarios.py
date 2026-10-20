from pathlib import Path

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    CLIENT_CREATION_SUITE,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
    REQUESTS_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs


def test_scenario_names_for_isolation_preserves_resolved_proxy_connect_defaults(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path, suite=PROXY_CONNECT_SUITE, scenarios=DEFAULT_PROXY_CONNECT_SCENARIOS)

    assert get_suite(args.suite).isolation_scenarios(args) == DEFAULT_PROXY_CONNECT_SCENARIOS.split(",")


def test_scenario_names_for_isolation_preserves_explicit_global_default(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path, suite=PROXY_CONNECT_SUITE, scenarios=DEFAULT_SCENARIOS)

    assert get_suite(args.suite).isolation_scenarios(args) == DEFAULT_SCENARIOS.split(",")


def test_client_creation_isolation_has_no_scenario_projection(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path, suite=CLIENT_CREATION_SUITE, scenarios=DEFAULT_SCENARIOS)

    assert get_suite(args.suite).isolation_scenarios(args) == []


def test_scenario_names_for_isolation_preserves_explicit_scenarios(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path, suite=REQUESTS_SUITE, scenarios="json-small,bytes-64k")

    assert get_suite(args.suite).isolation_scenarios(args) == ["json-small", "bytes-64k"]


def benchmark_args(output_dir: Path, *, suite: str, scenarios: str) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=suite,
        clients="foghttp",
        modes="async",
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(output_dir),
        scenarios=scenarios,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
        isolation="per-client-scenario",
    )
