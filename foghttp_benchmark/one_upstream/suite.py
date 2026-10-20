__all__ = ("run_one_upstream_suite", "select_clients")

import os

from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.one_upstream import (
    available_one_upstream_clients,
    one_upstream_cases,
    run_one_upstream_benchmarks,
    write_one_upstream_reports,
)
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.run_settling import run_settling_config
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import isolation_selection, parse_csv, parse_int_csv
from foghttp_benchmark.validation import validate_one_upstream_args


async def run_one_upstream_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building one-upstream benchmark plan")
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_one_upstream_clients(requested_clients, requested_modes)
    if not clients:
        msg = "one-upstream suite requires foghttp, httpx, or httpxyz clients"
        raise ValueError(msg)
    case_map = one_upstream_cases()
    requested_cases = parse_csv(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_one_upstream_args(
        args,
        requested_cases=requested_cases,
        case_map=case_map,
        concurrency_levels=concurrency_levels,
    )
    cases = [case_map[name] for name in requested_cases]
    settling_config = run_settling_config(os.environ)
    progress_status(progress, "Starting local benchmark server")
    async with benchmark_server() as base_url:
        results = await run_one_upstream_benchmarks(
            clients=clients,
            base_url=base_url,
            cases=cases,
            concurrency_levels=concurrency_levels,
            requests=args.requests,
            warmup=args.warmup,
            repeats=args.repeats,
            shuffle=not args.no_shuffle,
            seed=args.seed,
            settling_config=settling_config,
            progress=progress,
        )

    progress_status(progress, "Writing one-upstream reports")
    write_one_upstream_reports(results, skipped, args, settling_config=settling_config)


def select_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_one_upstream_clients(parse_csv(args.clients), parse_csv(args.modes))
    return isolation_selection(args, clients, skipped)
