__all__ = ("run_resource_backpressure_suite", "select_resource_clients")

from foghttp_benchmark.clients import available_clients
from foghttp_benchmark.isolation.models import ClientIsolationSelection
from foghttp_benchmark.models import BenchmarkArgs, ClientSpec
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.resource import resource_cases, run_resource_backpressure_benchmarks
from foghttp_benchmark.resource.reporting.reports import write_resource_reports
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import available_clients_for_suite, isolation_selection, parse_csv, parse_int_csv
from foghttp_benchmark.validation import validate_resource_backpressure_args


async def run_resource_backpressure_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    clients, skipped = available_clients_for_suite(args)
    progress_status(progress, "Building resource/backpressure benchmark plan")
    resource_clients, resource_skipped = foghttp_resource_clients(clients)
    skipped = {**skipped, **resource_skipped}
    if not resource_clients:
        msg = "resource-backpressure suite currently requires the foghttp client"
        raise ValueError(msg)
    case_map = resource_cases()
    requested_cases = parse_csv(args.scenarios)
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


def foghttp_resource_clients(clients: list[ClientSpec]) -> tuple[list[ClientSpec], dict[str, str]]:
    selected: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for spec in clients:
        if spec.name == "foghttp":
            selected.append(spec)
        else:
            skipped[f"{spec.mode}:{spec.name}"] = "resource-backpressure suite requires FogHTTP stats"
    return selected, skipped


def select_resource_clients(args: BenchmarkArgs) -> ClientIsolationSelection:
    clients, skipped = available_clients(parse_csv(args.clients), parse_csv(args.modes))
    selected, resource_skipped = foghttp_resource_clients(clients)
    return isolation_selection(args, selected, {**skipped, **resource_skipped})
