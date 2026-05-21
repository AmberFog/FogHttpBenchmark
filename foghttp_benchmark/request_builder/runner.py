__all__ = ("build_request_builder_plan", "run_request_builder_benchmarks")

import asyncio
import inspect
import random
import time
from typing import cast

from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.progress import ProgressReporter, progress_stage
from foghttp_benchmark.request_builder.clients import client_config_for_case, request_matches_case
from foghttp_benchmark.request_builder.models import (
    AsyncRequestBuilderAdapter,
    RequestBuilderCase,
    RequestBuilderClientSpec,
    RequestBuilderResult,
    RequestBuilderStats,
    SyncRequestBuilderAdapter,
)
from foghttp_benchmark.resources import ResourceSampler, take_resource_snapshot
from foghttp_benchmark.runner import percentile


SUCCESS_STATUS = 200


async def run_request_builder_benchmarks(
    *,
    clients: list[RequestBuilderClientSpec],
    base_url: str,
    cases: list[RequestBuilderCase],
    iterations: int,
    warmup: int,
    repeats: int,
    shuffle: bool,
    seed: int,
    progress: ProgressReporter | None = None,
) -> list[RequestBuilderResult]:
    plan = build_request_builder_plan(
        clients=clients,
        cases=cases,
        repeats=repeats,
        shuffle=shuffle,
        seed=seed,
    )
    results: list[RequestBuilderResult] = []
    with progress_stage(progress, "Request builder runs", total=len(plan)) as progress_step:
        for case, spec, repeat in plan:
            label = request_builder_progress_label(
                mode=spec.mode,
                client=spec.name,
                case=case.name,
                repeat=repeat,
                repeats=repeats,
            )
            progress_step.update(label)
            result = await run_request_builder_case(
                spec=spec,
                base_url=base_url,
                case=case,
                iterations=iterations,
                warmup=warmup,
                repeat=repeat,
            )
            results.append(result)
            progress_step.advance(label)
    return results


def build_request_builder_plan(
    *,
    clients: list[RequestBuilderClientSpec],
    cases: list[RequestBuilderCase],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[RequestBuilderCase, RequestBuilderClientSpec, int]]:
    plan = [(case, spec, repeat) for case in cases for spec in clients for repeat in range(1, repeats + 1)]
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def run_request_builder_case(
    *,
    spec: RequestBuilderClientSpec,
    base_url: str,
    case: RequestBuilderCase,
    iterations: int,
    warmup: int,
    repeat: int,
) -> RequestBuilderResult:
    if spec.mode == ASYNC_MODE:
        return await run_async_request_builder_case(
            spec=spec,
            base_url=base_url,
            case=case,
            iterations=iterations,
            warmup=warmup,
            repeat=repeat,
        )
    return await asyncio.to_thread(
        run_sync_request_builder_case,
        spec,
        base_url,
        case,
        iterations,
        warmup,
        repeat,
    )


async def run_async_request_builder_case(
    *,
    spec: RequestBuilderClientSpec,
    base_url: str,
    case: RequestBuilderCase,
    iterations: int,
    warmup: int,
    repeat: int,
) -> RequestBuilderResult:
    config = client_config_for_case(case, base_url=base_url)
    client = cast("AsyncRequestBuilderAdapter", spec.factory(config))
    try:
        await warmup_async(client, case, base_url, warmup)
        async with ResourceSampler() as sampler:
            started = time.perf_counter()
            stats = await measure_async(client, case, base_url, iterations)
            duration = time.perf_counter() - started
    finally:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

    return result_from_stats(
        spec=spec,
        case=case,
        iterations=iterations,
        repeat=repeat,
        duration=duration,
        stats=stats,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
    )


def run_sync_request_builder_case(
    spec: RequestBuilderClientSpec,
    base_url: str,
    case: RequestBuilderCase,
    iterations: int,
    warmup: int,
    repeat: int,
) -> RequestBuilderResult:
    config = client_config_for_case(case, base_url=base_url)
    client = cast("SyncRequestBuilderAdapter", spec.factory(config))
    try:
        warmup_sync(client, case, base_url, warmup)
        started = time.perf_counter()
        stats = measure_sync(client, case, base_url, iterations)
        duration = time.perf_counter() - started
        snapshot = take_resource_snapshot()
    finally:
        client.close()

    return result_from_stats(
        spec=spec,
        case=case,
        iterations=iterations,
        repeat=repeat,
        duration=duration,
        stats=stats,
        peak_rss_mb=snapshot.rss_mb,
        peak_threads=snapshot.threads,
        peak_fds=snapshot.fds,
    )


async def warmup_async(
    client: AsyncRequestBuilderAdapter,
    case: RequestBuilderCase,
    base_url: str,
    warmup: int,
) -> None:
    if warmup < 1:
        return
    await measure_async(client, case, base_url, warmup)


def warmup_sync(
    client: SyncRequestBuilderAdapter,
    case: RequestBuilderCase,
    base_url: str,
    warmup: int,
) -> None:
    if warmup < 1:
        return
    measure_sync(client, case, base_url, warmup)


async def measure_async(
    client: AsyncRequestBuilderAdapter,
    case: RequestBuilderCase,
    base_url: str,
    iterations: int,
) -> RequestBuilderStats:
    latencies: list[float] = []
    error_types: dict[str, int] = {}
    for _index in range(iterations):
        started = time.perf_counter_ns()
        try:
            request = client.build(case, base_url)
            if not request_matches_case(case, request):
                increment(error_types, "check_failed")
            if case.kind == "send-prepared":
                status_code = await client.send(request)
                if status_code != SUCCESS_STATUS:
                    increment(error_types, f"status_{status_code}")
        except Exception as exc:  # noqa: BLE001
            increment(error_types, type(exc).__name__)
        finally:
            latencies.append((time.perf_counter_ns() - started) / 1_000_000)
    return RequestBuilderStats(latencies, sum(error_types.values()), error_types)


def measure_sync(
    client: SyncRequestBuilderAdapter,
    case: RequestBuilderCase,
    base_url: str,
    iterations: int,
) -> RequestBuilderStats:
    latencies: list[float] = []
    error_types: dict[str, int] = {}
    for _index in range(iterations):
        started = time.perf_counter_ns()
        try:
            request = client.build(case, base_url)
            if not request_matches_case(case, request):
                increment(error_types, "check_failed")
            if case.kind == "send-prepared":
                status_code = client.send(request)
                if status_code != SUCCESS_STATUS:
                    increment(error_types, f"status_{status_code}")
        except Exception as exc:  # noqa: BLE001
            increment(error_types, type(exc).__name__)
        finally:
            latencies.append((time.perf_counter_ns() - started) / 1_000_000)
    return RequestBuilderStats(latencies, sum(error_types.values()), error_types)


def result_from_stats(
    *,
    spec: RequestBuilderClientSpec,
    case: RequestBuilderCase,
    iterations: int,
    repeat: int,
    duration: float,
    stats: RequestBuilderStats,
    peak_rss_mb: float | None,
    peak_threads: int | None,
    peak_fds: int | None,
) -> RequestBuilderResult:
    latencies = sorted(stats.latencies_ms)
    ok_iterations = iterations - stats.errors
    return RequestBuilderResult(
        client=spec.name,
        mode=spec.mode,
        case=case.name,
        group=case.group,
        kind=case.kind,
        profile=case.profile,
        iterations=iterations,
        repeat=repeat,
        duration_s=duration,
        operations_per_second=ok_iterations / duration if duration > 0 else 0.0,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        errors=stats.errors,
        error_types=stats.error_types,
        peak_rss_mb=peak_rss_mb,
        peak_threads=peak_threads,
        peak_fds=peak_fds,
    )


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def request_builder_progress_label(
    *,
    mode: str,
    client: str,
    case: str,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {case} repeat={repeat}/{repeats}"
