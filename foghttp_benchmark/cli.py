__all__ = ("app", "main", "run_benchmark")

import asyncio
from typing import TYPE_CHECKING, Annotated

import typer

from foghttp_benchmark.clients import available_clients
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    CLIENT_CREATION_SUITE,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    REQUESTS_SUITE,
    RESULTS_DIR,
)
from foghttp_benchmark.creation import run_client_creation_benchmarks
from foghttp_benchmark.creation_reports import write_creation_reports
from foghttp_benchmark.models import BenchmarkArgs, ClientSpec
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.runner import build_plan, run_once
from foghttp_benchmark.scenarios import scenarios
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.validation import validate_client_creation_args, validate_request_benchmark_args, validate_suite


if TYPE_CHECKING:
    from foghttp_benchmark.models import RunResult


app = typer.Typer(
    add_completion=False,
    help="Compare FogHTTP with other Python HTTP clients on local HTTP/1.1 workloads.",
)


@app.command()
def main(
    suite: Annotated[
        str,
        typer.Option(help="Benchmark suite: requests or client-creation."),
    ] = REQUESTS_SUITE,
    clients: Annotated[str, typer.Option(help="Comma-separated clients to benchmark.")] = DEFAULT_CLIENTS,
    modes: Annotated[str, typer.Option(help="Comma-separated modes: async, sync.")] = DEFAULT_MODES,
    concurrency: Annotated[str, typer.Option(help="Comma-separated concurrency levels.")] = DEFAULT_CONCURRENCY,
    requests: Annotated[int, typer.Option(help="Measured requests per run.")] = DEFAULT_REQUESTS,
    warmup: Annotated[int, typer.Option(help="Warmup requests per run, excluded from metrics.")] = DEFAULT_WARMUP,
    repeats: Annotated[int, typer.Option(help="Measured repeats for each client/scenario/concurrency tuple.")] = (
        DEFAULT_REPEATS
    ),
    max_redirects: Annotated[int, typer.Option(help="Maximum redirects for redirect scenarios.")] = (
        DEFAULT_MAX_REDIRECTS
    ),
    seed: Annotated[int, typer.Option(help="Deterministic shuffle and data generation seed.")] = BENCHMARK_SEED,
    no_shuffle: Annotated[  # noqa: FBT002 - Typer exposes this as a named CLI flag.
        bool,
        typer.Option("--no-shuffle", help="Run benchmark plan in declaration order."),
    ] = False,
    output_dir: Annotated[str, typer.Option(help="Directory for JSON and Markdown reports.")] = str(RESULTS_DIR),
    scenarios: Annotated[str, typer.Option(help="Comma-separated benchmark scenarios.")] = DEFAULT_SCENARIOS,
    iterations: Annotated[int, typer.Option(help="Iterations for client creation benchmarks.")] = (
        DEFAULT_CREATION_ITERATIONS
    ),
    client_counts: Annotated[str, typer.Option(help="Comma-separated client counts for creation benchmarks.")] = (
        DEFAULT_CLIENT_COUNTS
    ),
) -> None:
    args = BenchmarkArgs(
        suite=suite,
        clients=clients,
        modes=modes,
        concurrency=concurrency,
        requests=requests,
        warmup=warmup,
        repeats=repeats,
        max_redirects=max_redirects,
        seed=seed,
        no_shuffle=no_shuffle,
        output_dir=output_dir,
        scenarios=scenarios,
        iterations=iterations,
        client_counts=client_counts,
    )
    try:
        asyncio.run(run_benchmark(args))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


async def run_benchmark(args: BenchmarkArgs) -> None:
    validate_suite(args.suite)
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_clients(requested_clients, requested_modes)
    if not clients:
        msg = f"No requested clients are available: {skipped}"
        raise ValueError(msg)

    if args.suite == CLIENT_CREATION_SUITE:
        await run_client_creation_suite(args, clients, skipped)
        return

    await run_request_suite(args, clients, skipped)


async def run_request_suite(args: BenchmarkArgs, clients: list[ClientSpec], skipped: dict[str, str]) -> None:
    scenario_map = scenarios()
    requested_scenarios = parse_csv(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_request_benchmark_args(
        args,
        requested_scenarios=requested_scenarios,
        scenario_map=scenario_map,
        concurrency_levels=concurrency_levels,
    )
    plan = build_plan(
        clients=clients,
        requested_scenarios=requested_scenarios,
        scenario_map=scenario_map,
        concurrency_levels=concurrency_levels,
        repeats=args.repeats,
        shuffle=not args.no_shuffle,
        seed=args.seed,
    )
    results: list[RunResult] = []

    async with benchmark_server() as base_url:
        for scenario, concurrency, spec, repeat in plan:
            result = await run_once(
                spec=spec,
                base_url=base_url,
                scenario=scenario,
                concurrency=concurrency,
                requests=args.requests,
                repeat=repeat,
                warmup=args.warmup,
                max_redirects=args.max_redirects,
            )
            results.append(result)

    write_reports(results, skipped, args)


async def run_client_creation_suite(args: BenchmarkArgs, clients: list[ClientSpec], skipped: dict[str, str]) -> None:
    client_counts = parse_int_csv(args.client_counts)
    validate_client_creation_args(args, client_counts=client_counts)
    scenario = scenarios()["json-small"]
    async with benchmark_server() as base_url:
        results = await run_client_creation_benchmarks(
            clients=clients,
            base_url=base_url,
            scenario=scenario,
            iterations=args.iterations,
            repeats=args.repeats,
            client_counts=client_counts,
            max_redirects=args.max_redirects,
            shuffle=not args.no_shuffle,
            seed=args.seed,
        )

    write_creation_reports(results, skipped, args)


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    try:
        return [int(item) for item in parse_csv(value)]
    except ValueError as exc:
        msg = f"invalid integer list: {value}"
        raise ValueError(msg) from exc
