__all__ = ("finalize_merged_report", "run_response_streaming_suite", "select_clients")

from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.report_finalization import MergedSuiteReport
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.streaming.cases import streaming_cases
from foghttp_benchmark.streaming.clients import available_streaming_clients
from foghttp_benchmark.streaming.finalization import merged_streaming_metadata
from foghttp_benchmark.streaming.reports import write_streaming_reports
from foghttp_benchmark.streaming.runner import run_response_streaming_benchmarks
from foghttp_benchmark.suite_selection import isolation_selection, parse_csv, parse_int_csv
from foghttp_benchmark.validation import validate_streaming_args


async def run_response_streaming_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building response streaming benchmark plan")
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_streaming_clients(requested_clients, requested_modes)
    if not clients:
        msg = "response-streaming suite requires clients with comparable streaming support"
        raise ValueError(msg)
    case_map = streaming_cases()
    requested_cases = parse_csv(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_streaming_args(
        args,
        requested_cases=requested_cases,
        case_map=case_map,
        concurrency_levels=concurrency_levels,
        requests=args.requests,
    )
    cases = [case_map[name] for name in requested_cases]
    progress_status(progress, "Starting local benchmark server")
    async with benchmark_server() as base_url:
        results = await run_response_streaming_benchmarks(
            clients=clients,
            base_url=base_url,
            cases=cases,
            concurrency_levels=concurrency_levels,
            requests=args.requests,
            warmup=args.warmup,
            repeats=args.repeats,
            shuffle=not args.no_shuffle,
            seed=args.seed,
            progress=progress,
        )

    progress_status(progress, "Writing response streaming reports")
    write_streaming_reports(results, skipped, args)


def select_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_streaming_clients(parse_csv(args.clients), parse_csv(args.modes))
    return isolation_selection(args, clients, skipped)


def finalize_merged_report(rows: list[JsonObject], children_metadata: list[JsonObject]) -> MergedSuiteReport:
    return MergedSuiteReport(rows, merged_streaming_metadata(children_metadata))
