__all__ = (
    "build_plan",
    "run_once",
)

import gc
import inspect
import random
import time

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.constants import DEFAULT_MAX_REDIRECTS
from foghttp_benchmark.load import run_load
from foghttp_benchmark.models import ClientConfig, ClientSpec, LoadResult, RunResult, Scenario
from foghttp_benchmark.progress import INNER_MILESTONE_PERCENT, ProgressReporter, is_progress_enabled, progress_stage
from foghttp_benchmark.resources import ResourceSampler


def build_plan(
    *,
    clients: list[ClientSpec],
    requested_scenarios: list[str],
    scenario_map: dict[str, Scenario],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[Scenario, int, ClientSpec, int]]:
    plan: list[tuple[Scenario, int, ClientSpec, int]] = []
    for scenario_name in requested_scenarios:
        scenario = scenario_map.get(scenario_name)
        if scenario is None:
            continue
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((scenario, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def run_once(
    *,
    spec: ClientSpec,
    base_url: str,
    scenario: Scenario,
    concurrency: int,
    requests: int,
    repeat: int,
    warmup: int,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    progress: ProgressReporter | None = None,
    progress_label: str | None = None,
) -> RunResult:
    request_limit = scenario.request_limit or concurrency
    config = ClientConfig(
        concurrency=concurrency,
        request_limit=request_limit,
        per_origin_request_limit=request_limit,
        follow_redirects=scenario.follow_redirects,
        max_redirects=max_redirects,
    )
    client = spec.factory(config)
    url = base_url + scenario.path
    label = progress_label or f"{spec.mode}/{spec.name} {scenario.name} concurrency={concurrency} repeat={repeat}"

    try:
        warmup_result = await run_load_with_progress(
            client,
            scenario,
            url,
            concurrency,
            warmup,
            collect=False,
            progress=progress,
            stage_name=f"Warmup load: {label}",
        )
        gc.collect()
        cpu_start = time.process_time()
        started = time.perf_counter()
        async with ResourceSampler() as sampler:
            load_result = await run_load_with_progress(
                client,
                scenario,
                url,
                concurrency,
                requests,
                collect=True,
                progress=progress,
                stage_name=f"Measured load: {label}",
            )
        duration = time.perf_counter() - started
        cpu = time.process_time() - cpu_start
        latencies = sorted(load_result.latencies_ms)
        client_stats = client.stats()
    finally:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

    ok_requests = requests - load_result.errors
    return RunResult(
        client=spec.name,
        mode=spec.mode,
        scenario=scenario.name,
        concurrency=concurrency,
        request_limit=request_limit,
        requests=requests,
        repeat=repeat,
        duration_s=duration,
        requests_per_second=requests / duration if duration > 0 else 0.0,
        ok_requests_per_second=ok_requests / duration if duration > 0 else 0.0,
        ok_requests=ok_requests,
        p50_ms=percentile(latencies, 50),
        p90_ms=percentile(latencies, 90),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        min_ms=latencies[0] if latencies else 0.0,
        max_ms=latencies[-1] if latencies else 0.0,
        errors=load_result.errors,
        warmup_errors=warmup_result.errors,
        error_types=load_result.error_types,
        warmup_error_types=warmup_result.error_types,
        process_cpu_s=cpu,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
        client_stats=client_stats,
    )


async def run_load_with_progress(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressReporter | None,
    stage_name: str,
) -> LoadResult:
    if requests == 0 or not is_progress_enabled(progress):
        return await run_load(client, scenario, url, concurrency, requests, collect=collect)
    with progress_stage(
        progress,
        stage_name,
        total=requests,
        milestone_percent=INNER_MILESTONE_PERCENT,
        plain_output="heartbeat",
    ) as progress_step:
        return await run_load(
            client,
            scenario,
            url,
            concurrency,
            requests,
            collect=collect,
            progress=progress_step,
        )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
    return values[index]
