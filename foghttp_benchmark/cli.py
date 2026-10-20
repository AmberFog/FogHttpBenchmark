__all__ = ("app", "compare", "main")

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from foghttp_benchmark.application import execution
from foghttp_benchmark.compare.reports import build_comparison, write_or_print_compare_report
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_ONE_UPSTREAM_SCENARIOS,
    DEFAULT_PROXY_CONNECT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_REQUESTS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_PROXY_CONNECT_WARMUP,
    DEFAULT_REPEATS,
    DEFAULT_REQUEST_BUILDER_SCENARIOS,
    DEFAULT_REQUESTS,
    DEFAULT_RESOURCE_SCENARIOS,
    DEFAULT_SCENARIOS,
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_STREAMING_SCENARIOS,
    DEFAULT_WARMUP,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
    RESULTS_DIR,
)
from foghttp_benchmark.models import BenchmarkArgs


app = typer.Typer(
    add_completion=False,
    help="Compare FogHTTP with other Python HTTP clients on local HTTP/1.1 workloads.",
    invoke_without_command=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    *,
    suite: Annotated[
        str,
        typer.Option(
            help=(
                "Benchmark suite: requests, client-creation, resource-backpressure, one-upstream, "
                "request-builder, compressed-response, response-streaming, or proxy-connect."
            ),
        ),
    ] = REQUESTS_SUITE,
    clients: Annotated[str, typer.Option(help="Comma-separated clients to benchmark.")] = DEFAULT_CLIENTS,
    modes: Annotated[str, typer.Option(help="Comma-separated modes: async, sync.")] = DEFAULT_MODES,
    concurrency: Annotated[
        str,
        typer.Option(help="Comma-separated concurrency levels. Omitted: suite/profile defaults.", show_default=False),
    ] = DEFAULT_CONCURRENCY,
    requests: Annotated[
        int,
        typer.Option(help="Measured requests per run. Omitted: suite/profile defaults.", show_default=False),
    ] = DEFAULT_REQUESTS,
    warmup: Annotated[
        int,
        typer.Option(
            help="Warmup requests or iterations per run, excluded from metrics. Omitted: suite/profile defaults.",
            show_default=False,
        ),
    ] = DEFAULT_WARMUP,
    repeats: Annotated[int, typer.Option(help="Measured repeats for each client/scenario/concurrency tuple.")] = (
        DEFAULT_REPEATS
    ),
    max_redirects: Annotated[int, typer.Option(help="Maximum redirects for redirect scenarios.")] = (
        DEFAULT_MAX_REDIRECTS
    ),
    seed: Annotated[int, typer.Option(help="Deterministic shuffle and data generation seed.")] = BENCHMARK_SEED,
    no_shuffle: Annotated[
        bool,
        typer.Option("--no-shuffle", help="Run benchmark plan in declaration order."),
    ] = False,
    output_dir: Annotated[str, typer.Option(help="Directory for JSON and Markdown reports.")] = str(RESULTS_DIR),
    scenarios: Annotated[
        str,
        typer.Option(help="Comma-separated benchmark scenarios. Omitted: suite/profile defaults.", show_default=False),
    ] = DEFAULT_SCENARIOS,
    iterations: Annotated[int, typer.Option(help="Iterations for client creation and request builder benchmarks.")] = (
        DEFAULT_CREATION_ITERATIONS
    ),
    client_counts: Annotated[str, typer.Option(help="Comma-separated client counts for creation benchmarks.")] = (
        DEFAULT_CLIENT_COUNTS
    ),
    streaming_profile: Annotated[
        str,
        typer.Option(
            help=(
                "Response-streaming profile: default, lifecycle, or async-bytes (requests=rounds, iterations=batches)."
            ),
        ),
    ] = "default",
    streaming_payload_bytes: Annotated[
        int,
        typer.Option(help="Async-bytes payload size in bytes, at most 1 MiB."),
    ] = 1_048_576,
    streaming_server_write_bytes: Annotated[
        int,
        typer.Option(help="Async-bytes server write size; independent of client deliveries."),
    ] = 65_536,
    streaming_server_delay_s: Annotated[
        float,
        typer.Option(help="Async-bytes server delay between writes, in seconds (0..0.1)."),
    ] = 0.0,
    streaming_read_bytes: Annotated[
        int | None,
        typer.Option(help="Async-bytes explicit HTTPX read size; omitted means native, mandatory for FogHTTP."),
    ] = None,
    streaming_consumer_delay_s: Annotated[
        float,
        typer.Option(help="Async-bytes consumer delay between delivered chunks, in seconds (0..1)."),
    ] = 0.0,
    streaming_instrumentation: Annotated[
        str,
        typer.Option(help="Async-bytes instrumentation: control or diagnostic (bounded await/consumer trace)."),
    ] = "control",
    streaming_profiler_label: Annotated[
        str | None,
        typer.Option(help="Declare an external profiler; requires diagnostic instrumentation."),
    ] = None,
    streaming_profiler: Annotated[
        str,
        typer.Option(
            help=(
                "Async-bytes profiler: none, cprofile, sample-client/server or perf-client/server (Linux); "
                "diagnostics only."
            ),
        ),
    ] = "none",
    streaming_perf_sample_frequency_hz: Annotated[
        int,
        typer.Option(
            help="Async-bytes perf sample frequency: 499 Hz (default) or opt-in 1999 Hz; active perf required.",
        ),
    ] = 499,
    streaming_chunk_sample_cap: Annotated[
        int,
        typer.Option(help="Async-bytes first-N chunk/gap records per stream, between 1 and 128."),
    ] = 128,
    streaming_minimum_duration_s: Annotated[
        float,
        typer.Option(
            help="Async-bytes continuous load target: 0=fixed rounds, otherwise 1..5 seconds; stream cap remains hard.",
        ),
    ] = 0.0,
    streaming_max_window_streams: Annotated[
        int,
        typer.Option(help="Async-bytes duration window hard limit of complete streams, between 20 and 2048."),
    ] = 2048,
    streaming_server_observations: Annotated[
        bool,
        typer.Option(
            "--streaming-server-observations/--no-streaming-server-observations",
            help="Record server body write/drain clocks; compare observer impact separately.",
        ),
    ] = False,
    show_progress: Annotated[
        bool,
        typer.Option("--progress/--no-progress", help="Show benchmark stages and run progress."),
    ] = True,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    args = BenchmarkArgs(
        suite=suite,
        clients=clients,
        modes=modes,
        concurrency=concurrency,
        requests=requests,
        warmup=warmup,
        repeats=repeats,
        max_redirects=max_redirects,
        seed=seed,
        no_shuffle=no_shuffle,
        output_dir=output_dir,
        scenarios=scenarios,
        iterations=iterations,
        client_counts=client_counts,
        streaming_profile=streaming_profile,
        streaming_payload_bytes=streaming_payload_bytes,
        streaming_server_write_bytes=streaming_server_write_bytes,
        streaming_server_delay_s=streaming_server_delay_s,
        streaming_read_bytes=streaming_read_bytes,
        streaming_consumer_delay_s=streaming_consumer_delay_s,
        streaming_instrumentation=streaming_instrumentation,
        streaming_profiler_label=streaming_profiler_label,
        streaming_profiler=streaming_profiler,
        streaming_perf_sample_frequency_hz=streaming_perf_sample_frequency_hz,
        streaming_chunk_sample_cap=streaming_chunk_sample_cap,
        streaming_minimum_duration_s=streaming_minimum_duration_s,
        streaming_max_window_streams=streaming_max_window_streams,
        streaming_server_observations=streaming_server_observations,
    )
    try:
        args = resolve_cli_defaults(ctx, args)
        asyncio.run(execution.run_benchmark(args, show_progress=show_progress))
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


def resolve_cli_defaults(context: typer.Context, args: BenchmarkArgs) -> BenchmarkArgs:
    """Resolve omitted CLI options once; BenchmarkArgs always contains effective values."""
    for name in (
        "streaming_payload_bytes",
        "streaming_server_write_bytes",
        "streaming_server_delay_s",
        "streaming_read_bytes",
        "streaming_consumer_delay_s",
        "streaming_instrumentation",
        "streaming_profiler_label",
        "streaming_profiler",
        "streaming_perf_sample_frequency_hz",
        "streaming_chunk_sample_cap",
        "streaming_minimum_duration_s",
        "streaming_max_window_streams",
        "streaming_server_observations",
    ):
        source = context.get_parameter_source(name)
        if source is not None and source.name != "DEFAULT" and args.streaming_profile != "async-bytes":
            msg = f"--{name.replace('_', '-')} requires --streaming-profile async-bytes"
            raise ValueError(msg)
    defaulted = {
        name
        for name in ("clients", "modes", "concurrency", "requests", "warmup", "iterations", "repeats", "scenarios")
        if (source := context.get_parameter_source(name)) is not None and source.name == "DEFAULT"
    }
    if args.streaming_profile == "default":
        scenario_defaults = {
            RESOURCE_BACKPRESSURE_SUITE: DEFAULT_RESOURCE_SCENARIOS,
            ONE_UPSTREAM_SUITE: DEFAULT_ONE_UPSTREAM_SCENARIOS,
            REQUEST_BUILDER_SUITE: DEFAULT_REQUEST_BUILDER_SCENARIOS,
            COMPRESSED_RESPONSE_SUITE: DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
            RESPONSE_STREAMING_SUITE: DEFAULT_STREAMING_SCENARIOS,
            PROXY_CONNECT_SUITE: DEFAULT_PROXY_CONNECT_SCENARIOS,
        }
        request_defaults = {
            RESPONSE_STREAMING_SUITE: DEFAULT_STREAMING_REQUESTS,
            PROXY_CONNECT_SUITE: DEFAULT_PROXY_CONNECT_REQUESTS,
        }
        return replace(
            args,
            scenarios=scenario_defaults.get(args.suite, args.scenarios) if "scenarios" in defaulted else args.scenarios,
            requests=request_defaults.get(args.suite, args.requests) if "requests" in defaulted else args.requests,
            warmup=DEFAULT_PROXY_CONNECT_WARMUP
            if args.suite == PROXY_CONNECT_SUITE and "warmup" in defaulted
            else args.warmup,
            concurrency=DEFAULT_PROXY_CONNECT_CONCURRENCY
            if args.suite == PROXY_CONNECT_SUITE and "concurrency" in defaulted
            else args.concurrency,
        )
    if args.streaming_profile not in {"lifecycle", "async-bytes"} or args.suite != RESPONSE_STREAMING_SUITE:
        msg = "The lifecycle/async-bytes streaming profiles require --suite response-streaming"
        raise ValueError(msg)
    return replace(
        args,
        clients="foghttp,httpx" if "clients" in defaulted else args.clients,
        modes=("async" if args.streaming_profile == "async-bytes" else "async,sync")
        if "modes" in defaulted
        else args.modes,
        concurrency="1,10" if "concurrency" in defaulted else args.concurrency,
        requests=20 if "requests" in defaulted else args.requests,
        warmup=2 if "warmup" in defaulted else args.warmup,
        iterations=5 if "iterations" in defaulted else args.iterations,
        repeats=3 if "repeats" in defaulted else args.repeats,
        scenarios=("stream-1m" if args.streaming_profile == "async-bytes" else "first-chunk-close-1m,stream-1m")
        if "scenarios" in defaulted
        else args.scenarios,
    )


@app.command()
def compare(
    old_report: Annotated[Path, typer.Argument(help="Baseline benchmark JSON report.")],
    new_report: Annotated[Path, typer.Argument(help="New benchmark JSON report.")],
    *,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write Markdown comparison to this path.")] = (
        None
    ),
    focus_client: Annotated[str, typer.Option(help="Client to compare across old and new reports.")] = "foghttp",
    top: Annotated[int, typer.Option(help="Number of top improvements/regressions to show.")] = 10,
    comparison_axis: Annotated[
        str | None,
        typer.Option(help="Explicitly allow the foghttp-source SHA axis; other conditions must match."),
    ] = None,
) -> None:
    if top < 1:
        msg = "top must be at least 1"
        raise typer.BadParameter(msg)

    try:
        comparison = build_comparison(
            old_report,
            new_report,
            focus_client=focus_client,
            top_n=top,
            comparison_axis=comparison_axis,
        )
        write_or_print_compare_report(comparison, output)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
