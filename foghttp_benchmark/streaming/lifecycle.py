__all__ = ("run_lifecycle_profile",)

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Literal, cast

from foghttp_benchmark.isolation.lifecycle import read_object, run_lifecycle_case
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.progress import ProgressReporter, progress_stage
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.attribution_reports import write_attribution_reports
from foghttp_benchmark.streaming.clients import available_streaming_clients
from foghttp_benchmark.streaming.lifecycle_models import (
    LifecycleConfig,
    build_lifecycle_plan,
    validate_lifecycle_case,
    validate_lifecycle_config,
)
from foghttp_benchmark.streaming.lifecycle_reports import write_lifecycle_reports


async def run_lifecycle_profile(args: BenchmarkArgs, *, progress: ProgressReporter | None = None) -> None:
    if args.suite != "response-streaming":
        msg = "Lifecycle profile belongs to the response-streaming suite"
        raise ValueError(msg)
    config = LifecycleConfig(warmup_rounds=args.warmup, batches=args.iterations, rounds_per_batch=args.requests)
    if args.streaming_profile == "async-bytes":
        config = LifecycleConfig(
            body_bytes=args.streaming_payload_bytes,
            server_write_bytes=args.streaming_server_write_bytes,
            warmup_rounds=args.warmup,
            batches=args.iterations,
            rounds_per_batch=args.requests,
            attribution=AttributionConfig(
                server_delay_s=args.streaming_server_delay_s,
                requested_client_read_bytes=args.streaming_read_bytes,
                consumer_delay_s=args.streaming_consumer_delay_s,
                instrumentation=cast("Literal['control', 'diagnostic']", args.streaming_instrumentation),
                profiler_label=args.streaming_profiler_label,
                profiler=cast(
                    "Literal['none', 'cprofile', 'sample-client', 'sample-server', 'perf-client', 'perf-server']",
                    args.streaming_profiler,
                ),
                perf_sample_frequency_hz=args.streaming_perf_sample_frequency_hz,
                chunk_sample_cap=args.streaming_chunk_sample_cap,
                minimum_duration_s=args.streaming_minimum_duration_s,
                max_window_streams=args.streaming_max_window_streams,
                server_observations=args.streaming_server_observations,
            ),
        )
    write_reports = write_attribution_reports if config.attribution is not None else write_lifecycle_reports
    validate_lifecycle_config(config)
    clients = args.clients.split(",")
    modes = args.modes.split(",")
    plan = build_lifecycle_plan(
        clients=clients,
        modes=modes,
        cases=args.scenarios.split(","),
        concurrency_levels=[int(value) for value in args.concurrency.split(",")],
        repeats=args.repeats,
        seed=args.seed,
        shuffle=not args.no_shuffle,
    )
    for case in plan:
        validate_lifecycle_case(case, config)
    _, skipped = available_streaming_clients(clients, modes)
    if skipped:
        msg = f"Lifecycle profile requires every selected client/mode: {skipped}"
        raise ValueError(msg)
    output = await asyncio.to_thread(Path(args.output_dir).resolve)
    results: list[JsonObject] = []
    with progress_stage(progress, "Isolated streaming lifecycle cases", total=len(plan)) as step:
        for case in plan:
            case_output = (
                output
                / "isolated"
                / f"{case.sequence:03d}-{case.mode}-{case.client}-{case.case}-c{case.concurrency}-r{case.repeat}"
            )
            try:
                result = await run_lifecycle_case(case, config, case_output)
            except asyncio.CancelledError as cancellation:
                try:
                    partial = await asyncio.to_thread(read_object, case_output / "receipt.json")
                except (OSError, TypeError, ValueError):
                    partial = {
                        "case": asdict(case),
                        "failure": "Lifecycle launcher cancelled before a receipt was saved",
                    }
                results.append(partial)
                try:
                    write_reports(results, args, config, plan)
                except (OSError, TypeError, ValueError) as report_error:
                    cancellation.add_note(f"Partial report write failed: {report_error}")
                raise
            results.append(result)
            write_reports(results, args, config, plan)
            step.advance(f"{case.mode}/{case.client}/{case.case} C{case.concurrency} repeat={case.repeat}")
            if result.get("failure"):
                msg = f"Lifecycle case failed: {result['failure']}; partial output retained in {case_output}"
                raise ValueError(msg)
