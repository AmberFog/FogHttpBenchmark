__all__ = ("build_child_args", "build_parser", "main")

import argparse
import asyncio
from collections.abc import Sequence

from foghttp_benchmark.cli import run_benchmark_child
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
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
from foghttp_benchmark.models import BenchmarkArgs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m foghttp_benchmark._child")
    parser.add_argument("--suite", default=REQUESTS_SUITE)
    parser.add_argument("--clients", required=True)
    parser.add_argument("--modes", default=DEFAULT_MODES)
    parser.add_argument("--concurrency", default=DEFAULT_CONCURRENCY)
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--max-redirects", type=int, default=DEFAULT_MAX_REDIRECTS)
    parser.add_argument("--seed", type=int, default=BENCHMARK_SEED)
    parser.add_argument("--no-shuffle", action="store_true")
    parser.add_argument("--output-dir", default=str(RESULTS_DIR))
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_CREATION_ITERATIONS)
    parser.add_argument("--client-counts", default=DEFAULT_CLIENT_COUNTS)

    progress_group = parser.add_mutually_exclusive_group()
    progress_group.add_argument("--progress", dest="show_progress", action="store_true")
    progress_group.add_argument("--no-progress", dest="show_progress", action="store_false")
    parser.set_defaults(show_progress=False)
    return parser


def build_child_args(namespace: argparse.Namespace) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=namespace.suite,
        clients=namespace.clients,
        modes=namespace.modes,
        concurrency=namespace.concurrency,
        requests=namespace.requests,
        warmup=namespace.warmup,
        repeats=namespace.repeats,
        max_redirects=namespace.max_redirects,
        seed=namespace.seed,
        no_shuffle=namespace.no_shuffle,
        output_dir=namespace.output_dir,
        scenarios=namespace.scenarios,
        iterations=namespace.iterations,
        client_counts=namespace.client_counts,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    try:
        asyncio.run(run_benchmark_child(build_child_args(namespace), show_progress=namespace.show_progress))
    except (TypeError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    main()
