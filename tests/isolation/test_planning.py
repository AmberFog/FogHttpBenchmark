from pathlib import Path

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    REQUESTS_SUITE,
)
from foghttp_benchmark.isolation.planning import (
    benchmark_child_command,
    build_client_isolation_plan,
    build_client_scenario_isolation_plan,
)
from foghttp_benchmark.models import BenchmarkArgs


def test_child_command_does_not_expose_isolation_bypass_flag(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path)

    command = benchmark_child_command(args, client="foghttp", output_dir=tmp_path / "child")

    assert command[1:3] == ["-m", "foghttp_benchmark._child"]
    assert command[command.index("--clients") + 1] == "foghttp"
    assert "--isolation" not in command
    assert "--no-progress" in command
    assert "--no-shuffle" in command


def test_client_isolation_plan_uses_stable_sequential_child_directories(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path)

    plan = build_client_isolation_plan(args, ["foghttp", "httpx"])

    assert [item.sequence for item in plan] == [1, 2]
    assert [item.client for item in plan] == ["foghttp", "httpx"]
    assert plan[0].output_dir == tmp_path.resolve() / "isolated" / "001-foghttp"
    assert plan[1].output_dir == tmp_path.resolve() / "isolated" / "002-httpx"


def test_client_scenario_isolation_plan_splits_clients_and_scenarios(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path)

    plan = build_client_scenario_isolation_plan(args, ["foghttp", "httpx"], ["direct-http", "proxy-connect"])

    assert [(item.sequence, item.client, item.scenario) for item in plan] == [
        (1, "foghttp", "direct-http"),
        (2, "foghttp", "proxy-connect"),
        (3, "httpx", "direct-http"),
        (4, "httpx", "proxy-connect"),
    ]
    assert plan[0].output_dir == tmp_path.resolve() / "isolated" / "001-foghttp-direct-http"
    assert plan[1].command[plan[1].command.index("--scenarios") + 1] == "proxy-connect"


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=REQUESTS_SUITE,
        clients="foghttp,httpx",
        modes="async",
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=True,
        output_dir=str(output_dir),
        scenarios=DEFAULT_SCENARIOS,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
