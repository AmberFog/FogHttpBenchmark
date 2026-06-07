__all__ = (
    "validate_client_creation_args",
    "validate_one_upstream_args",
    "validate_request_benchmark_args",
    "validate_request_builder_args",
    "validate_resource_backpressure_args",
    "validate_streaming_args",
    "validate_suite",
)

from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    ONE_UPSTREAM_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs, Scenario
from foghttp_benchmark.one_upstream.models import OneUpstreamCase
from foghttp_benchmark.request_builder.models import RequestBuilderCase
from foghttp_benchmark.resource.scenarios import ResourceCase
from foghttp_benchmark.streaming.models import StreamingCase


def validate_suite(suite: str) -> None:
    if suite not in {
        REQUESTS_SUITE,
        CLIENT_CREATION_SUITE,
        RESOURCE_BACKPRESSURE_SUITE,
        ONE_UPSTREAM_SUITE,
        REQUEST_BUILDER_SUITE,
        COMPRESSED_RESPONSE_SUITE,
        RESPONSE_STREAMING_SUITE,
    }:
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


def validate_resource_backpressure_args(
    args: BenchmarkArgs,
    *,
    requested_cases: list[str],
    case_map: dict[str, ResourceCase],
    concurrency_levels: list[int],
) -> None:
    errors: list[str] = []
    if args.requests < 1:
        errors.append("--requests must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if not concurrency_levels:
        errors.append("--concurrency must contain at least one value")
    if any(value < 1 for value in concurrency_levels):
        errors.append("--concurrency values must be >= 1")

    unknown_cases = [name for name in requested_cases if name not in case_map]
    if unknown_cases:
        errors.append(f"unknown resource cases: {', '.join(unknown_cases)}")

    if errors:
        msg = "Invalid resource/backpressure benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def validate_one_upstream_args(
    args: BenchmarkArgs,
    *,
    requested_cases: list[str],
    case_map: dict[str, OneUpstreamCase],
    concurrency_levels: list[int],
) -> None:
    errors: list[str] = []
    if args.requests < 1:
        errors.append("--requests must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if not concurrency_levels:
        errors.append("--concurrency must contain at least one value")
    if any(value < 1 for value in concurrency_levels):
        errors.append("--concurrency values must be >= 1")

    unknown_cases = [name for name in requested_cases if name not in case_map]
    if unknown_cases:
        errors.append(f"unknown one-upstream cases: {', '.join(unknown_cases)}")

    if errors:
        msg = "Invalid one-upstream benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def validate_request_builder_args(
    args: BenchmarkArgs,
    *,
    requested_cases: list[str],
    case_map: dict[str, RequestBuilderCase],
) -> None:
    errors: list[str] = []
    if args.iterations < 1:
        errors.append("--iterations must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")

    unknown_cases = [name for name in requested_cases if name not in case_map]
    if unknown_cases:
        errors.append(f"unknown request-builder cases: {', '.join(unknown_cases)}")

    if errors:
        msg = "Invalid request-builder benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def validate_streaming_args(
    args: BenchmarkArgs,
    *,
    requested_cases: list[str],
    case_map: dict[str, StreamingCase],
    concurrency_levels: list[int],
    requests: int,
) -> None:
    errors: list[str] = []
    if requests < 1:
        errors.append("--requests must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if not concurrency_levels:
        errors.append("--concurrency must contain at least one value")
    if any(value < 1 for value in concurrency_levels):
        errors.append("--concurrency values must be >= 1")

    unknown_cases = [name for name in requested_cases if name not in case_map]
    if unknown_cases:
        errors.append(f"unknown response-streaming cases: {', '.join(unknown_cases)}")

    if errors:
        msg = "Invalid response-streaming benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)
