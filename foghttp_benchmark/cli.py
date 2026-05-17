__all__ = ("app", "compare", "main", "run_benchmark")

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from foghttp_benchmark.clients import available_clients
from foghttp_benchmark.compare.reports import build_comparison, write_or_print_compare_report
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
    DEFAULT_RESOURCE_SCENARIOS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESULTS_DIR,
)
from foghttp_benchmark.creation import run_client_creation_benchmarks
from foghttp_benchmark.creation_reports import write_creation_reports
from foghttp_benchmark.models import BenchmarkArgs, ClientSpec
from foghttp_benchmark.progress import BenchmarkProgress, ProgressReporter, progress_stage, progress_status
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.resource import resource_cases, run_resource_backpressure_benchmarks
from foghttp_benchmark.resource.reporting.reports import write_resource_reports
from foghttp_benchmark.runner import build_plan, run_once
from foghttp_benchmark.scenarios import scenarios
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.validation import (
    validate_client_creation_args,
    validate_request_benchmark_args,
    validate_resource_backpressure_args,
    validate_suite,
)


if TYPE_CHECKING:
    from foghttp_benchmark.models import RunResult


app = typer.Typer(
    add_completion=False,
    help="Compare FogHTTP with other Python HTTP clients on local HTTP/1.1 workloads.",
    invoke_without_command=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    suite: Annotated[
        str,
        typer.Option(help="Benchmark suite: requests, client-creation, or resource-backpressure."),
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
    show_progress: Annotated[  # noqa: FBT002 - Typer exposes this as named CLI flags.
        bool,
        typer.Option("--progress/--no-progress", help="Show benchmark stages and run progress."),
    ] = True,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
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
        asyncio.run(run_benchmark(args, show_progress=show_progress))
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def compare(
    old_report: Annotated[Path, typer.Argument(help="Baseline benchmark JSON report.")],
    new_report: Annotated[Path, typer.Argument(help="New benchmark JSON report.")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write Markdown comparison to this path.")] = (
        None
    ),
    focus_client: Annotated[str, typer.Option(help="Client to compare across old and new reports.")] = "foghttp",
    top: Annotated[int, typer.Option(help="Number of top improvements/regressions to show.")] = 10,
) -> None:
    if top < 1:
        msg = "top must be at least 1"
        raise typer.BadParameter(msg)

    try:
        comparison = build_comparison(
            old_report,
            new_report,
            focus_client=focus_client,
            top_n=top,
        )
        write_or_print_compare_report(comparison, output)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


async def run_benchmark(args: BenchmarkArgs, *, show_progress: bool = True) -> None:
    with BenchmarkProgress(enabled=show_progress) as progress:
        progress_status(progress, f"Preparing {args.suite} benchmark")
        validate_suite(args.suite)
        requested_clients = parse_csv(args.clients)
        requested_modes = parse_csv(args.modes)
        clients, skipped = available_clients(requested_clients, requested_modes)
        if not clients:
            msg = f"No requested clients are available: {skipped}"
            raise ValueError(msg)

        if args.suite == CLIENT_CREATION_SUITE:
            await run_client_creation_suite(args, clients, skipped, progress=progress)
            return
        if args.suite == RESOURCE_BACKPRESSURE_SUITE:
            await run_resource_backpressure_suite(args, clients, skipped, progress=progress)
            return

        await run_request_suite(args, clients, skipped, progress=progress)


async def run_request_suite(
    args: BenchmarkArgs,
    clients: list[ClientSpec],
    skipped: dict[str, str],
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building request benchmark plan")
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

    progress_status(progress, "Starting local benchmark server")
    async with benchmark_server() as base_url:
        with progress_stage(progress, "Request runs", total=len(plan)) as progress_step:
            for scenario, concurrency, spec, repeat in plan:
                label = request_progress_label(
                    mode=spec.mode,
                    client=spec.name,
                    scenario=scenario.name,
                    concurrency=concurrency,
                    repeat=repeat,
                    repeats=args.repeats,
                )
                progress_step.update(label)
                result = await run_once(
                    spec=spec,
                    base_url=base_url,
                    scenario=scenario,
                    concurrency=concurrency,
                    requests=args.requests,
                    repeat=repeat,
                    warmup=args.warmup,
                    max_redirects=args.max_redirects,
                    progress=progress,
                    progress_label=label,
                )
                results.append(result)
                progress_step.advance(label)

    progress_status(progress, "Writing request benchmark reports")
    write_reports(results, skipped, args)


async def run_client_creation_suite(
    args: BenchmarkArgs,
    clients: list[ClientSpec],
    skipped: dict[str, str],
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building client lifecycle benchmark plan")
    client_counts = parse_int_csv(args.client_counts)
    validate_client_creation_args(args, client_counts=client_counts)
    scenario = scenarios()["json-small"]
    progress_status(progress, "Starting local benchmark server")
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
            progress=progress,
        )

    progress_status(progress, "Writing client lifecycle reports")
    write_creation_reports(results, skipped, args)


async def run_resource_backpressure_suite(
    args: BenchmarkArgs,
    clients: list[ClientSpec],
    skipped: dict[str, str],
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building resource/backpressure benchmark plan")
    resource_clients, resource_skipped = foghttp_resource_clients(clients)
    skipped = {**skipped, **resource_skipped}
    if not resource_clients:
        msg = "resource-backpressure suite currently requires the foghttp client"
        raise ValueError(msg)
    case_map = resource_cases()
    requested_cases = resource_scenario_names(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_resource_backpressure_args(
        args,
        requested_cases=requested_cases,
        case_map=case_map,
        concurrency_levels=concurrency_levels,
    )
    cases = [case_map[name] for name in requested_cases]
    progress_status(progress, "Starting local benchmark servers")
    async with benchmark_server() as base_url, benchmark_server() as secondary_base_url:
        results = await run_resource_backpressure_benchmarks(
            clients=resource_clients,
            base_url=base_url,
            secondary_base_url=secondary_base_url,
            cases=cases,
            concurrency_levels=concurrency_levels,
            requests=args.requests,
            warmup=args.warmup,
            repeats=args.repeats,
            max_redirects=args.max_redirects,
            shuffle=not args.no_shuffle,
            seed=args.seed,
            progress=progress,
        )

    progress_status(progress, "Writing resource/backpressure reports")
    write_resource_reports(results, skipped, args)


def request_progress_label(
    *,
    mode: str,
    client: str,
    scenario: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {scenario} concurrency={concurrency} repeat={repeat}/{repeats}"


def foghttp_resource_clients(clients: list[ClientSpec]) -> tuple[list[ClientSpec], dict[str, str]]:
    selected: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for spec in clients:
        if spec.name == "foghttp":
            selected.append(spec)
        else:
            skipped[f"{spec.mode}:{spec.name}"] = "resource-backpressure suite requires FogHTTP stats"
    return selected, skipped


def resource_scenario_names(value: str) -> list[str]:
    if value == DEFAULT_SCENARIOS:
        return parse_csv(DEFAULT_RESOURCE_SCENARIOS)
    return parse_csv(value)


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    try:
        return [int(item) for item in parse_csv(value)]
    except ValueError as exc:
        msg = f"invalid integer list: {value}"
        raise ValueError(msg) from exc
