__all__ = (
    "validate_client_creation_args",
    "validate_request_benchmark_args",
    "validate_suite",
)

from foghttp_benchmark.constants import CLIENT_CREATION_SUITE, REQUESTS_SUITE
from foghttp_benchmark.models import BenchmarkArgs, Scenario


def validate_suite(suite: str) -> None:
    if suite not in {REQUESTS_SUITE, CLIENT_CREATION_SUITE}:
        msg = f"unknown benchmark suite: {suite}"
        raise ValueError(msg)


def validate_request_benchmark_args(
    args: BenchmarkArgs,
    *,
    requested_scenarios: list[str],
    scenario_map: dict[str, Scenario],
    concurrency_levels: list[int],
) -> None:
    errors: list[str] = []
    if args.requests < 1:
        errors.append("--requests must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if args.max_redirects < 1:
        errors.append("--max-redirects must be >= 1")
    if not concurrency_levels:
        errors.append("--concurrency must contain at least one value")
    if any(value < 1 for value in concurrency_levels):
        errors.append("--concurrency values must be >= 1")

    unknown_scenarios = [name for name in requested_scenarios if name not in scenario_map]
    if unknown_scenarios:
        errors.append(f"unknown scenarios: {', '.join(unknown_scenarios)}")

    if errors:
        msg = "Invalid benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def validate_client_creation_args(
    args: BenchmarkArgs,
    *,
    client_counts: list[int],
) -> None:
    errors: list[str] = []
    if args.iterations < 1:
        errors.append("--iterations must be >= 1")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if args.max_redirects < 1:
        errors.append("--max-redirects must be >= 1")
    if not client_counts:
        errors.append("--client-counts must contain at least one value")
    if any(value < 1 for value in client_counts):
        errors.append("--client-counts values must be >= 1")

    if errors:
        msg = "Invalid client creation benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)
