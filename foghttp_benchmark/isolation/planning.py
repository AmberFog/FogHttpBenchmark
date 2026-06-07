__all__ = (
    "benchmark_child_command",
    "build_client_isolation_plan",
    "build_client_scenario_isolation_plan",
)

from pathlib import Path
import re
import sys

from foghttp_benchmark.isolation.models import (
    ClientIsolationPlanItem,
)
from foghttp_benchmark.models import BenchmarkArgs


SAFE_DIR_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def build_client_isolation_plan(args: BenchmarkArgs, clients: list[str]) -> list[ClientIsolationPlanItem]:
    base_dir = Path(args.output_dir).resolve() / "isolated"
    return [
        ClientIsolationPlanItem(
            sequence=index,
            client=client,
            scenario=None,
            output_dir=child_output_dir(base_dir, index, client, scenario=None),
            command=benchmark_child_command(
                args,
                client=client,
                output_dir=child_output_dir(base_dir, index, client, scenario=None),
            ),
        )
        for index, client in enumerate(clients, start=1)
    ]


def build_client_scenario_isolation_plan(
    args: BenchmarkArgs,
    clients: list[str],
    scenarios: list[str],
) -> list[ClientIsolationPlanItem]:
    base_dir = Path(args.output_dir).resolve() / "isolated"
    plan: list[ClientIsolationPlanItem] = []
    sequence = 1
    for client in clients:
        for scenario in scenarios:
            output_dir = child_output_dir(base_dir, sequence, client, scenario=scenario)
            plan.append(
                ClientIsolationPlanItem(
                    sequence=sequence,
                    client=client,
                    scenario=scenario,
                    output_dir=output_dir,
                    command=benchmark_child_command(args, client=client, output_dir=output_dir, scenario=scenario),
                ),
            )
            sequence += 1
    return plan


def child_output_dir(base_dir: Path, sequence: int, client: str, *, scenario: str | None) -> Path:
    safe_client = SAFE_DIR_CHARS.sub("-", client).strip("-") or "client"
    if scenario is None:
        return base_dir / f"{sequence:03d}-{safe_client}"
    safe_scenario = SAFE_DIR_CHARS.sub("-", scenario).strip("-") or "scenario"
    return base_dir / f"{sequence:03d}-{safe_client}-{safe_scenario}"


def benchmark_child_command(
    args: BenchmarkArgs,
    *,
    client: str,
    output_dir: Path,
    scenario: str | None = None,
) -> list[str]:
    scenario_arg = args.scenarios if scenario is None else scenario
    command = [
        sys.executable,
        "-m",
        "foghttp_benchmark._child",
        "--suite",
        args.suite,
        "--clients",
        client,
        "--modes",
        args.modes,
        "--concurrency",
        args.concurrency,
        "--requests",
        str(args.requests),
        "--warmup",
        str(args.warmup),
        "--repeats",
        str(args.repeats),
        "--max-redirects",
        str(args.max_redirects),
        "--seed",
        str(args.seed),
        "--output-dir",
        str(output_dir),
        "--scenarios",
        scenario_arg,
        "--iterations",
        str(args.iterations),
        "--client-counts",
        args.client_counts,
        "--no-progress",
    ]
    if args.no_shuffle:
        command.append("--no-shuffle")
    return command
