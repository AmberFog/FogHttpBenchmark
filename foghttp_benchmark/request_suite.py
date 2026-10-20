__all__ = ("run_request_suite",)

import os
from typing import TYPE_CHECKING

from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.progress import ProgressReporter, progress_stage, progress_status
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.run_settling import run_settling_config, settle_after_run
from foghttp_benchmark.runner import build_plan, run_once
from foghttp_benchmark.scenarios import scenarios
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import available_clients_for_suite, parse_csv, parse_int_csv
from foghttp_benchmark.validation import validate_request_benchmark_args


if TYPE_CHECKING:
    from foghttp_benchmark.models import RunResult


async def run_request_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    clients, skipped = available_clients_for_suite(args)
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
    settling_config = run_settling_config(os.environ)

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
                await settle_after_run(result.client_stats, settling_config, progress=progress)

    progress_status(progress, "Writing request benchmark reports")
    write_reports(results, skipped, args, settling_config=settling_config)


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
