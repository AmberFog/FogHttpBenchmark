from pathlib import Path

from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, build_lifecycle_plan


def lifecycle_plan(**overrides: object) -> list[LifecycleCase]:
    parameters = {
        "clients": ["foghttp", "httpx"],
        "modes": ["async", "sync"],
        "cases": ["first-chunk-close-1m", "stream-1m"],
        "concurrency_levels": [1, 10],
        "repeats": 3,
        "seed": 42,
        "shuffle": True,
    }
    parameters.update(overrides)
    return build_lifecycle_plan(**parameters)


def lifecycle_args(output: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite="response-streaming",
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=1,
        warmup=0,
        repeats=1,
        max_redirects=0,
        seed=42,
        no_shuffle=True,
        output_dir=str(output),
        scenarios="stream-1m",
        iterations=1,
        client_counts="1",
        streaming_profile="lifecycle",
    )
