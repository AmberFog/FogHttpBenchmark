__all__ = ("run_resource_backpressure_benchmarks",)

import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
from queue import Empty, Queue
import random
import time

from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.load import merge_load_results, outcome_matches, run_load
from foghttp_benchmark.models import (
    ClientConfig,
    ClientSpec,
    ClientStats,
    LoadResult,
    ResourceBackpressureResult,
    ResponseOutcome,
    Scenario,
)
from foghttp_benchmark.progress import (
    INNER_MILESTONE_PERCENT,
    ProgressReporter,
    ProgressStep,
    is_progress_enabled,
    progress_stage,
)
from foghttp_benchmark.resource.scenarios import ResourceCase
from foghttp_benchmark.resources import ResourceSampler
from foghttp_benchmark.runner import percentile


async def run_resource_backpressure_benchmarks(
    *,
    clients: list[ClientSpec],
    base_url: str,
    secondary_base_url: str,
    cases: list[ResourceCase],
    concurrency_levels: list[int],
    requests: int,
    warmup: int,
    repeats: int,
    max_redirects: int,
    shuffle: bool,
    seed: int,
    progress: ProgressReporter | None = None,
) -> list[ResourceBackpressureResult]:
    plan = build_resource_plan(
        clients=clients,
        cases=cases,
        concurrency_levels=concurrency_levels,
        repeats=repeats,
        shuffle=shuffle,
        seed=seed,
    )
    results: list[ResourceBackpressureResult] = []
    with progress_stage(progress, "Resource/backpressure runs", total=len(plan)) as progress_step:
        for case, concurrency, spec, repeat in plan:
            label = resource_progress_label(
                mode=spec.mode,
                client=spec.name,
                case=case.name,
                concurrency=concurrency,
                repeat=repeat,
                repeats=repeats,
            )
            progress_step.update(label)
            result = await run_resource_case(
                spec=spec,
                base_url=base_url,
                secondary_base_url=secondary_base_url,
                case=case,
                concurrency=concurrency,
                requests=requests,
                warmup=warmup,
                repeat=repeat,
                max_redirects=max_redirects,
                progress=progress,
                progress_label=label,
            )
            results.append(result)
            progress_step.advance(label)
    return results


def build_resource_plan(
    *,
    clients: list[ClientSpec],
    cases: list[ResourceCase],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[ResourceCase, int, ClientSpec, int]]:
    plan: list[tuple[ResourceCase, int, ClientSpec, int]] = []
    for case in cases:
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((case, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


def resource_progress_label(
    *,
    mode: str,
    client: str,
    case: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {case} concurrency={concurrency} repeat={repeat}/{repeats}"


async def run_resource_case(
    *,
    spec: ClientSpec,
    base_url: str,
    secondary_base_url: str,
    case: ResourceCase,
    concurrency: int,
    requests: int,
    warmup: int,
    repeat: int,
    max_redirects: int,
    progress: ProgressReporter | None = None,
    progress_label: str | None = None,
) -> ResourceBackpressureResult:
    max_pending_requests = case.max_pending_requests
    if max_pending_requests is None:
        max_pending_requests = max(case.request_limit * 10, concurrency)
    config = ClientConfig(
        concurrency=concurrency,
        request_limit=case.request_limit,
        per_origin_request_limit=case.per_origin_request_limit,
        max_pending_requests=max_pending_requests,
        max_response_body_size=case.max_response_body_size,
        max_buffered_response_bytes=case.max_buffered_response_bytes,
        follow_redirects=False,
        max_redirects=max_redirects,
        pool_timeout_s=case.pool_timeout_s,
        total_timeout_s=case.total_timeout_s,
    )
    scenario = scenario_from_case(case)
    url = base_url + case.path
    secondary_url = None if case.secondary_path is None else secondary_base_url + case.secondary_path
    label = progress_label or f"{spec.mode}/{spec.name} {case.name} concurrency={concurrency} repeat={repeat}"
    client = spec.factory(config)
    load_result = LoadResult([], 0, {})
    warmup_result = LoadResult([], 0, {})
    duration = 0.0
    peak_active_requests: int | None = None
    peak_pending_requests: int | None = None
    peak_buffered_response_bytes: int | None = None
    client_stats: ClientStats | None = None
    recovery_ok: bool | None = None
    recovery_error: str | None = None
    sampler: ResourceSampler | None = None

    try:
        warmup_result = await run_case_load_with_progress(
            client,
            scenario,
            url,
            secondary_url,
            concurrency,
            warmup,
            collect=False,
            progress=progress,
            stage_name=f"Warmup resource load: {label}",
        )
        started = time.perf_counter()
        async with ResourceSampler() as sampler, TransportStatsSampler(client) as stats_sampler:
            load_result = await run_case_load_with_progress(
                client,
                scenario,
                url,
                secondary_url,
                concurrency,
                requests,
                collect=True,
                progress=progress,
                stage_name=f"Measured resource load: {label}",
            )
        duration = time.perf_counter() - started
        peak_active_requests = stats_sampler.peak_active_requests
        peak_pending_requests = stats_sampler.peak_pending_requests
        peak_buffered_response_bytes = stats_sampler.peak_buffered_response_bytes
        client_stats = client.stats()
        recovery_ok, recovery_error = await run_recovery_check(
            client=client,
            base_url=base_url,
            recovery_path=case.recovery_path,
        )
    finally:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

    latencies = sorted(load_result.latencies_ms)
    ok_requests = requests - load_result.errors
    return ResourceBackpressureResult(
        client=spec.name,
        mode=spec.mode,
        scenario=case.name,
        concurrency=concurrency,
        request_limit=case.request_limit,
        per_origin_request_limit=case.per_origin_request_limit,
        max_pending_requests=max_pending_requests,
        max_response_body_size=case.max_response_body_size,
        max_buffered_response_bytes=case.max_buffered_response_bytes,
        pool_timeout_s=case.pool_timeout_s,
        requests=requests,
        warmup=warmup,
        repeat=repeat,
        duration_s=duration,
        ok_requests=ok_requests,
        errors=load_result.errors,
        warmup_errors=warmup_result.errors,
        error_types=load_result.error_types,
        warmup_error_types=warmup_result.error_types,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        peak_rss_mb=None if sampler is None else sampler.peak_rss_mb,
        peak_threads=None if sampler is None else sampler.peak_threads,
        peak_fds=None if sampler is None else sampler.peak_fds,
        peak_active_requests=peak_active_requests,
        peak_pending_requests=peak_pending_requests,
        peak_buffered_response_bytes=peak_buffered_response_bytes,
        client_stats=client_stats,
        recovery_ok=recovery_ok,
        recovery_error=recovery_error,
    )


def scenario_from_case(case: ResourceCase) -> Scenario:
    return Scenario(
        name=case.name,
        method="GET",
        path=case.path,
        expected_json_keys=case.expected_json_keys,
        expected_content_length=case.expected_content_length,
        description=case.description,
    )


async def run_recovery_check(
    *,
    client: AsyncClientAdapter | SyncClientAdapter,
    base_url: str,
    recovery_path: str | None,
) -> tuple[bool | None, str | None]:
    if recovery_path is None:
        return None, None
    scenario = recovery_scenario(recovery_path)
    url = base_url + recovery_path
    try:
        outcome = await request_once(client, scenario, url)
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__
    return outcome_matches(scenario, outcome), None


async def run_case_load(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
    secondary_url: str | None,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> LoadResult:
    if secondary_url is None:
        return await run_load(client, scenario, url, concurrency, requests, collect=collect, progress=progress)
    if requests == 0:
        return LoadResult([], 0, {})
    if isinstance(client, AsyncClientAdapter):
        return await run_async_mixed_origin_load(
            client,
            scenario,
            url,
            secondary_url,
            concurrency,
            requests,
            collect=collect,
            progress=progress,
        )
    return await asyncio.to_thread(
        run_sync_mixed_origin_load,
        client,
        scenario,
        url,
        secondary_url,
        concurrency,
        requests,
        collect=collect,
        progress=progress,
    )


async def run_case_load_with_progress(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
    secondary_url: str | None,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressReporter | None,
    stage_name: str,
) -> LoadResult:
    if requests == 0 or not is_progress_enabled(progress):
        return await run_case_load(
            client,
            scenario,
            url,
            secondary_url,
            concurrency,
            requests,
            collect=collect,
        )
    with progress_stage(
        progress,
        stage_name,
        total=requests,
        milestone_percent=INNER_MILESTONE_PERCENT,
        plain_output="heartbeat",
    ) as progress_step:
        return await run_case_load(
            client,
            scenario,
            url,
            secondary_url,
            concurrency,
            requests,
            collect=collect,
            progress=progress_step,
        )


async def run_async_mixed_origin_load(
    client: AsyncClientAdapter,
    scenario: Scenario,
    url: str,
    secondary_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> LoadResult:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(requests):
        queue.put_nowait(index)

    async def worker() -> LoadResult:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return LoadResult(latencies, sum(error_types.values()), error_types)

            target_url = url if index % 2 == 0 else secondary_url
            started = time.perf_counter_ns()
            try:
                outcome = await client.request(scenario, target_url)
                if not outcome_matches(scenario, outcome):
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
    return merge_load_results(results)


def run_sync_mixed_origin_load(
    client: SyncClientAdapter,
    scenario: Scenario,
    url: str,
    secondary_url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> LoadResult:
    queue: Queue[int] = Queue()
    for index in range(requests):
        queue.put_nowait(index)

    def worker() -> LoadResult:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                index = queue.get_nowait()
            except Empty:
                return LoadResult(latencies, sum(error_types.values()), error_types)

            target_url = url if index % 2 == 0 else secondary_url
            started = time.perf_counter_ns()
            try:
                outcome = client.request(scenario, target_url)
                if not outcome_matches(scenario, outcome):
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
    return merge_load_results(results)


def recovery_scenario(path: str) -> Scenario:
    if path.startswith("/bytes/"):
        return Scenario(
            name="resource-recovery",
            method="GET",
            path=path,
            expected_content_length=int(path.rsplit("/", 1)[1]),
        )
    return Scenario(
        name="resource-recovery",
        method="GET",
        path=path,
        expected_json_keys=("ok", "message", "items"),
    )


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


async def request_once(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
) -> ResponseOutcome:
    if isinstance(client, AsyncClientAdapter):
        return await client.request(scenario, url)
    return await asyncio.to_thread(client.request, scenario, url)


class TransportStatsSampler:
    def __init__(self, client: AsyncClientAdapter | SyncClientAdapter, interval: float = 0.002) -> None:
        self.client = client
        self.interval = interval
        self.peak_active_requests: int | None = None
        self.peak_pending_requests: int | None = None
        self.peak_buffered_response_bytes: int | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "TransportStatsSampler":
        self._running = True
        self._task = asyncio.create_task(self._sample_loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._running = False
        if self._task is not None:
            await self._task
        self.sample()

    async def _sample_loop(self) -> None:
        while self._running:
            self.sample()
            await asyncio.sleep(self.interval)

    def sample(self) -> None:
        stats = self.client.stats()
        if stats is None:
            return
        active = stats.get("active_requests")
        pending = stats.get("pending_requests")
        buffered_response_bytes = stats.get("buffered_response_bytes")
        if isinstance(active, int):
            self.peak_active_requests = max(self.peak_active_requests or 0, active)
        if isinstance(pending, int):
            self.peak_pending_requests = max(self.peak_pending_requests or 0, pending)
        if isinstance(buffered_response_bytes, int):
            self.peak_buffered_response_bytes = max(self.peak_buffered_response_bytes or 0, buffered_response_bytes)
