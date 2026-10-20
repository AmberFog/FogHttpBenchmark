__all__ = ("run_request_builder_suite", "select_clients")

from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.request_builder import (
    available_request_builder_clients,
    request_builder_cases,
    run_request_builder_benchmarks,
    write_request_builder_reports,
)
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import isolation_selection, parse_csv
from foghttp_benchmark.validation import validate_request_builder_args


async def run_request_builder_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building request builder benchmark plan")
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_request_builder_clients(requested_clients, requested_modes)
    if not clients:
        msg = "request-builder suite requires foghttp, httpx, or httpxyz clients"
        raise ValueError(msg)
    case_map = request_builder_cases()
    requested_cases = parse_csv(args.scenarios)
    validate_request_builder_args(args, requested_cases=requested_cases, case_map=case_map)
    cases = [case_map[name] for name in requested_cases]
    base_url = "http://127.0.0.1:1"
    if any(case.kind == "send-prepared" for case in cases):
        progress_status(progress, "Starting local benchmark server")
        async with benchmark_server() as server_base_url:
            results = await run_request_builder_benchmarks(
                clients=clients,
                base_url=server_base_url,
                cases=cases,
                iterations=args.iterations,
                warmup=args.warmup,
                repeats=args.repeats,
                shuffle=not args.no_shuffle,
                seed=args.seed,
                progress=progress,
            )
    else:
        results = await run_request_builder_benchmarks(
            clients=clients,
            base_url=base_url,
            cases=cases,
            iterations=args.iterations,
            warmup=args.warmup,
            repeats=args.repeats,
            shuffle=not args.no_shuffle,
            seed=args.seed,
            progress=progress,
        )

    progress_status(progress, "Writing request builder reports")
    write_request_builder_reports(results, skipped, args)


def select_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_request_builder_clients(parse_csv(args.clients), parse_csv(args.modes))
    return isolation_selection(args, clients, skipped)
