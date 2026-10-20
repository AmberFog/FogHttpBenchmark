from dataclasses import replace
from pathlib import Path

import pytest

from foghttp_benchmark._child import build_child_args, build_parser
from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_WARMUP,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.isolation.planning import (
    benchmark_child_command,
    build_client_isolation_plan,
    build_client_scenario_isolation_plan,
)
from tests.isolation.args_factory import benchmark_args


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


@pytest.mark.parametrize(
    "suite",
    [
        REQUESTS_SUITE,
        CLIENT_CREATION_SUITE,
        RESOURCE_BACKPRESSURE_SUITE,
        ONE_UPSTREAM_SUITE,
        REQUEST_BUILDER_SUITE,
        COMPRESSED_RESPONSE_SUITE,
        RESPONSE_STREAMING_SUITE,
        PROXY_CONNECT_SUITE,
    ],
)
@pytest.mark.parametrize(("warmup", "no_shuffle"), [(DEFAULT_WARMUP, True), (0, False)])
@pytest.mark.parametrize("scenario", [None, "selected-case"])
def test_child_command_preserves_effective_arguments_without_reapplying_defaults(
    tmp_path: Path,
    suite: str,
    warmup: int,
    *,
    no_shuffle: bool,
    scenario: str | None,
) -> None:
    args = replace(benchmark_args(tmp_path), suite=suite, warmup=warmup, no_shuffle=no_shuffle)
    output_dir = tmp_path / "child"

    command = benchmark_child_command(args, client="httpx", output_dir=output_dir, scenario=scenario)
    namespace = build_parser().parse_args(command[3:])
    child_args = build_child_args(namespace)

    assert child_args == replace(
        args,
        clients="httpx",
        output_dir=str(output_dir),
        scenarios=args.scenarios if scenario is None else scenario,
    )
    assert namespace.show_progress is False
