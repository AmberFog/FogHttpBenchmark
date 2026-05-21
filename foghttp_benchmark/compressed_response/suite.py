__all__ = ("run_compressed_response_suite",)

from typing import TYPE_CHECKING

from foghttp_benchmark.compressed_response.scenarios import compressed_response_scenarios
from foghttp_benchmark.constants import DEFAULT_COMPRESSED_RESPONSE_SCENARIOS, DEFAULT_SCENARIOS
from foghttp_benchmark.progress import ProgressReporter, progress_stage, progress_status
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.runner import build_plan, run_once
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.validation import validate_request_benchmark_args


if TYPE_CHECKING:
    from foghttp_benchmark.models import BenchmarkArgs, ClientSpec, RunResult


async def run_compressed_response_suite(
    args: "BenchmarkArgs",
    clients: list["ClientSpec"],
    skipped: dict[str, str],
    *,
    progress: ProgressReporter | None = None,
) -> None:
    progress_status(progress, "Building compressed response benchmark plan")
    scenario_map = compressed_response_scenarios()
    requested_scenarios = compressed_response_scenario_names(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    validate_request_benchmark_args(
        args,
        requested_scenarios=requested_scenarios,
        scenario_map=scenario_map,
        concurrency_levels=concurrency_levels,
    )
    plan = build_plan(
        clients=clients,
        requested_scenarios=requested_scenarios,
        scenario_map=scenario_map,
        concurrency_levels=concurrency_levels,
        repeats=args.repeats,
        shuffle=not args.no_shuffle,
        seed=args.seed,
    )
    results: list[RunResult] = []

    progress_status(progress, "Starting local benchmark server")
    async with benchmark_server() as base_url:
        with progress_stage(progress, "Compressed response runs", total=len(plan)) as progress_step:
            for scenario, concurrency, spec, repeat in plan:
                label = compressed_response_progress_label(
                    mode=spec.mode,
                    client=spec.name,
                    scenario=scenario.name,
                    concurrency=concurrency,
                    repeat=repeat,
                    repeats=args.repeats,
                )
                progress_step.update(label)
                result = await run_once(
                    spec=spec,
                    base_url=base_url,
                    scenario=scenario,
                    concurrency=concurrency,
                    requests=args.requests,
                    repeat=repeat,
                    warmup=args.warmup,
                    max_redirects=args.max_redirects,
                    progress=progress,
                    progress_label=label,
                )
                results.append(result)
                progress_step.advance(label)

    progress_status(progress, "Writing compressed response reports")
    write_reports(results, skipped, args)


def compressed_response_scenario_names(value: str) -> list[str]:
    if value == DEFAULT_SCENARIOS:
        return parse_csv(DEFAULT_COMPRESSED_RESPONSE_SCENARIOS)
    return parse_csv(value)


def compressed_response_progress_label(
    *,
    mode: str,
    client: str,
    scenario: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {scenario} concurrency={concurrency} repeat={repeat}/{repeats}"


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    try:
        return [int(item) for item in parse_csv(value)]
    except ValueError as exc:
        msg = f"invalid integer list: {value}"
        raise ValueError(msg) from exc
