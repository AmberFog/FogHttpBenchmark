__all__ = ("run_client_creation_suite",)

from foghttp_benchmark.creation.runner import run_client_creation_benchmarks
from foghttp_benchmark.creation_reports import write_creation_reports
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.progress import ProgressReporter, progress_status
from foghttp_benchmark.scenarios import scenarios
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.suite_selection import available_clients_for_suite, parse_int_csv
from foghttp_benchmark.validation import validate_client_creation_args


async def run_client_creation_suite(
    args: BenchmarkArgs,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    clients, skipped = available_clients_for_suite(args)
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
