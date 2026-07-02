__all__ = ("build_one_upstream_plan", "run_one_upstream_benchmarks")

import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
from queue import Empty, Queue
import random
import time
from typing import cast

from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.one_upstream.clients import client_config_for_case
from foghttp_benchmark.one_upstream.models import (
    AsyncOneUpstreamAdapter,
    OneUpstreamCase,
    OneUpstreamClientSpec,
    OneUpstreamResult,
    OneUpstreamStats,
    SyncOneUpstreamAdapter,
)
from foghttp_benchmark.progress import (
    INNER_MILESTONE_PERCENT,
    ProgressReporter,
    ProgressStep,
    is_progress_enabled,
    progress_stage,
)
from foghttp_benchmark.resources import ResourceSampler
from foghttp_benchmark.run_settling import RunSettlingConfig, settle_after_run
from foghttp_benchmark.runner import percentile


async def run_one_upstream_benchmarks(
    *,
    clients: list[OneUpstreamClientSpec],
    base_url: str,
    cases: list[OneUpstreamCase],
    concurrency_levels: list[int],
    requests: int,
    warmup: int,
    repeats: int,
    shuffle: bool,
    seed: int,
    settling_config: RunSettlingConfig,
    progress: ProgressReporter | None = None,
) -> list[OneUpstreamResult]:
    plan = build_one_upstream_plan(
        clients=clients,
        cases=cases,
        concurrency_levels=concurrency_levels,
        repeats=repeats,
        shuffle=shuffle,
        seed=seed,
    )
    results: list[OneUpstreamResult] = []
    with progress_stage(progress, "One-upstream runs", total=len(plan)) as progress_step:
        for case, concurrency, spec, repeat in plan:
            label = one_upstream_progress_label(
                mode=spec.mode,
                client=spec.name,
                case=case.name,
                concurrency=concurrency,
                repeat=repeat,
                repeats=repeats,
            )
            progress_step.update(label)
            result = await run_one_upstream_case(
                spec=spec,
                base_url=base_url,
                case=case,
                concurrency=concurrency,
                requests=requests,
                warmup=warmup,
                repeat=repeat,
                progress=progress,
                progress_label=label,
            )
            results.append(result)
            progress_step.advance(label)
            await settle_after_run(result.client_stats, settling_config, progress=progress)
    return results


def build_one_upstream_plan(
    *,
    clients: list[OneUpstreamClientSpec],
    cases: list[OneUpstreamCase],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[OneUpstreamCase, int, OneUpstreamClientSpec, int]]:
    plan: list[tuple[OneUpstreamCase, int, OneUpstreamClientSpec, int]] = []
    for case in cases:
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((case, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def run_one_upstream_case(
    *,
    spec: OneUpstreamClientSpec,
    base_url: str,
    case: OneUpstreamCase,
    concurrency: int,
    requests: int,
    warmup: int,
    repeat: int,
    progress: ProgressReporter | None = None,
    progress_label: str | None = None,
) -> OneUpstreamResult:
    config = client_config_for_case(case, base_url=base_url, concurrency=concurrency)
    client = spec.factory(config)
    label = progress_label or f"{spec.mode}/{spec.name} {case.name} concurrency={concurrency} repeat={repeat}"
    client_stats = None
    try:
        warmup_result = await run_load_with_progress(
            client,
            case,
            base_url,
            concurrency,
            warmup,
            collect=False,
            progress=progress,
            stage_name=f"Warmup one-upstream load: {label}",
            mode=spec.mode,
        )
        started = time.perf_counter()
        async with ResourceSampler() as sampler:
            load_result = await run_load_with_progress(
                client,
                case,
                base_url,
                concurrency,
                requests,
                collect=True,
                progress=progress,
                stage_name=f"Measured one-upstream load: {label}",
                mode=spec.mode,
            )
        duration = time.perf_counter() - started
        client_stats = client.stats()
    finally:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

    latencies = sorted(load_result.latencies_ms)
    ok_requests = requests - load_result.errors
    return OneUpstreamResult(
        client=spec.name,
        mode=spec.mode,
        case=case.name,
        group=case.group,
        profile=case.profile,
        concurrency=concurrency,
        request_limit=concurrency,
        requests=requests,
        repeat=repeat,
        duration_s=duration,
        requests_per_second=requests / duration if duration > 0 else 0.0,
        ok_requests_per_second=ok_requests / duration if duration > 0 else 0.0,
        ok_requests=ok_requests,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        errors=load_result.errors,
        warmup_errors=warmup_result.errors,
        error_types=load_result.error_types,
        warmup_error_types=warmup_result.error_types,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
        client_stats=client_stats,
    )


async def run_load_with_progress(
    client: AsyncOneUpstreamAdapter | SyncOneUpstreamAdapter,
    case: OneUpstreamCase,
    base_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressReporter | None,
    stage_name: str,
    mode: str,
) -> OneUpstreamStats:
    if requests == 0 or not is_progress_enabled(progress):
        return await run_one_upstream_load(client, case, base_url, concurrency, requests, collect=collect, mode=mode)
    with progress_stage(
        progress,
        stage_name,
        total=requests,
        milestone_percent=INNER_MILESTONE_PERCENT,
        plain_output="heartbeat",
    ) as progress_step:
        return await run_one_upstream_load(
            client,
            case,
            base_url,
            concurrency,
            requests,
            collect=collect,
            mode=mode,
            progress=progress_step,
        )


async def run_one_upstream_load(
    client: AsyncOneUpstreamAdapter | SyncOneUpstreamAdapter,
    case: OneUpstreamCase,
    base_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    mode: str,
    progress: ProgressStep | None = None,
) -> OneUpstreamStats:
    if requests == 0:
        return OneUpstreamStats([], 0, {})
    if mode == ASYNC_MODE:
        return await run_async_one_upstream_load(
            client,
            case,
            base_url,
            concurrency,
            requests,
            collect=collect,
            progress=progress,
        )
    return await asyncio.to_thread(
        run_sync_one_upstream_load,
        client,
        case,
        base_url,
        concurrency,
        requests,
        collect=collect,
        progress=progress,
    )


async def run_async_one_upstream_load(
    client: AsyncOneUpstreamAdapter | SyncOneUpstreamAdapter,
    case: OneUpstreamCase,
    base_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> OneUpstreamStats:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(requests):
        queue.put_nowait(index)
    async_client = cast("AsyncOneUpstreamAdapter", client)

    async def worker() -> OneUpstreamStats:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return OneUpstreamStats(latencies, sum(error_types.values()), error_types)

            started = time.perf_counter_ns()
            try:
                if not await async_client.request(case, base_url):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, requests))]
    await queue.join()
    results = await asyncio.gather(*workers)
    return merge_results(results)


def run_sync_one_upstream_load(
    client: AsyncOneUpstreamAdapter | SyncOneUpstreamAdapter,
    case: OneUpstreamCase,
    base_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> OneUpstreamStats:
    queue: Queue[int] = Queue()
    for index in range(requests):
        queue.put_nowait(index)
    sync_client = cast("SyncOneUpstreamAdapter", client)

    def worker() -> OneUpstreamStats:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return OneUpstreamStats(latencies, sum(error_types.values()), error_types)

            started = time.perf_counter_ns()
            try:
                if not sync_client.request(case, base_url):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    with ThreadPoolExecutor(max_workers=min(concurrency, requests)) as executor:
        results = list(executor.map(lambda _index: worker(), range(min(concurrency, requests))))
    return merge_results(results)


def merge_results(results: list[OneUpstreamStats]) -> OneUpstreamStats:
    latencies: list[float] = []
    error_types: dict[str, int] = {}
    for result in results:
        latencies.extend(result.latencies_ms)
        for key, count in result.error_types.items():
            error_types[key] = error_types.get(key, 0) + count
    return OneUpstreamStats(latencies, sum(error_types.values()), error_types)


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def one_upstream_progress_label(
    *,
    mode: str,
    client: str,
    case: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {case} concurrency={concurrency} repeat={repeat}/{repeats}"
