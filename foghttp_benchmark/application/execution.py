__all__ = ("run_benchmark", "run_benchmark_child")

from dataclasses import replace

from foghttp_benchmark.application import composition
from foghttp_benchmark.isolation.execution import run_isolated_benchmark
from foghttp_benchmark.isolation.models import CHILD_PROCESS_ISOLATION
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.progress import BenchmarkProgress, progress_status
from foghttp_benchmark.provenance import research_provenance_from_env
from foghttp_benchmark.streaming.lifecycle import run_lifecycle_profile


async def run_benchmark(args: BenchmarkArgs, *, show_progress: bool = True) -> None:
    provenance = research_provenance_from_env(check_remote=True)
    if args.streaming_profile == "async-bytes" and provenance is None:
        msg = "Async bytes research requires a freshly verified FOGHTTP_BENCHMARK_RESEARCH_MANIFEST"
        raise ValueError(msg)
    with BenchmarkProgress(enabled=show_progress) as progress:
        progress_status(progress, f"Preparing {args.suite} benchmark")
        suite = composition.get_suite(args.suite)
        if args.streaming_profile in {"lifecycle", "async-bytes"}:
            await run_lifecycle_profile(args, progress=progress)
        elif args.streaming_profile == "default":
            await run_isolated_benchmark(
                args,
                select_clients=suite.select_clients,
                scenario_names=suite.isolation_scenarios,
                finalizer=suite.finalize_report,
                progress=progress,
            )
        else:
            msg = f"Unknown streaming profile: {args.streaming_profile}"
            raise ValueError(msg)


async def run_benchmark_child(args: BenchmarkArgs, *, show_progress: bool = False) -> None:
    research_provenance_from_env()
    if args.streaming_profile != "default":
        msg = "Lifecycle profiles require the parent-owned process launcher"
        raise ValueError(msg)
    child_args = replace(args, isolation=CHILD_PROCESS_ISOLATION)
    with BenchmarkProgress(enabled=show_progress) as progress:
        progress_status(progress, f"Preparing isolated child {child_args.suite} benchmark")
        await composition.run_benchmark_suite(child_args, progress=progress)
