__all__ = (
    "build_proxy_connect_plan",
    "run_proxy_connect_benchmarks",
)

import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import inspect
import os
from queue import Empty, Queue
import random
import time
from typing import cast

from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.progress import (
    INNER_MILESTONE_PERCENT,
    ProgressReporter,
    ProgressStep,
    is_progress_enabled,
    progress_stage,
)
from foghttp_benchmark.proxy_connect.models import (
    AsyncProxyConnectAdapter,
    ProxyConnectCase,
    ProxyConnectClientConfig,
    ProxyConnectClientSpec,
    ProxyConnectEndpoints,
    ProxyConnectLoadResult,
    ProxyConnectResult,
    ProxyStatsDelta,
    SyncProxyConnectAdapter,
)
from foghttp_benchmark.proxy_connect.proxy_server import ProxyServerStats
from foghttp_benchmark.resources import ResourceSampler
from foghttp_benchmark.runner import percentile


PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


async def run_proxy_connect_benchmarks(
    *,
    clients: list[ProxyConnectClientSpec],
    endpoints: ProxyConnectEndpoints,
    proxy_stats: ProxyServerStats,
    cases: list[ProxyConnectCase],
    concurrency_levels: list[int],
    requests: int,
    warmup: int,
    repeats: int,
    shuffle: bool,
    seed: int,
    progress: ProgressReporter | None = None,
) -> list[ProxyConnectResult]:
    plan = build_proxy_connect_plan(
        clients=clients,
        cases=cases,
        concurrency_levels=concurrency_levels,
        repeats=repeats,
        shuffle=shuffle,
        seed=seed,
    )
    results: list[ProxyConnectResult] = []
    with progress_stage(progress, "Proxy CONNECT runs", total=len(plan)) as progress_step:
        for case, concurrency, spec, repeat in plan:
            label = proxy_connect_progress_label(
                mode=spec.mode,
                client=spec.name,
                case=case.name,
                concurrency=concurrency,
                repeat=repeat,
                repeats=repeats,
            )
            progress_step.update(label)
            result = await run_proxy_connect_case(
                spec=spec,
                endpoints=endpoints,
                proxy_stats=proxy_stats,
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
    return results


def build_proxy_connect_plan(
    *,
    clients: list[ProxyConnectClientSpec],
    cases: list[ProxyConnectCase],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[ProxyConnectCase, int, ProxyConnectClientSpec, int]]:
    plan: list[tuple[ProxyConnectCase, int, ProxyConnectClientSpec, int]] = []
    for case in cases:
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((case, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def run_proxy_connect_case(
    *,
    spec: ProxyConnectClientSpec,
    endpoints: ProxyConnectEndpoints,
    proxy_stats: ProxyServerStats,
    case: ProxyConnectCase,
    concurrency: int,
    requests: int,
    warmup: int,
    repeat: int,
    progress: ProgressReporter | None = None,
    progress_label: str | None = None,
) -> ProxyConnectResult:
    config = ProxyConnectClientConfig(
        concurrency=concurrency,
        request_limit=concurrency,
        proxy_url=endpoints.proxy_url,
        ca_cert_path=endpoints.ca_cert_path,
        config=case.config,
        lifecycle=case.lifecycle,
    )
    label = progress_label or f"{spec.mode}/{spec.name} {case.name} concurrency={concurrency} repeat={repeat}"
    url = target_url(case, endpoints)
    with proxy_environment(case, endpoints.proxy_url):
        client = spec.factory(config)
        try:
            start_proxy = proxy_stats.snapshot()
            warmup_result = await run_load_with_progress(
                client,
                case,
                url,
                concurrency,
                warmup,
                collect=False,
                progress=progress,
                stage_name=f"Warmup proxy load: {label}",
                mode=spec.mode,
            )
            measured_proxy_start = proxy_stats.snapshot()
            started = time.perf_counter()
            async with ResourceSampler() as sampler:
                load_result = await run_load_with_progress(
                    client,
                    case,
                    url,
                    concurrency,
                    requests,
                    collect=True,
                    progress=progress,
                    stage_name=f"Measured proxy load: {label}",
                    mode=spec.mode,
                )
            duration = time.perf_counter() - started
            measured_proxy_end = proxy_stats.snapshot()
            client_stats = client.stats()
        finally:
            close_result = client.close()
            if inspect.isawaitable(close_result):
                await close_result
        total_proxy_end = proxy_stats.snapshot()

    measured_proxy = proxy_delta(measured_proxy_start, measured_proxy_end)
    total_proxy = proxy_delta(start_proxy, total_proxy_end)
    error_types = dict(load_result.error_types)
    proxy_error = proxy_usage_error(
        case=case,
        requests=requests,
        measured_proxy=measured_proxy,
        total_proxy=total_proxy,
    )
    if proxy_error is not None:
        error_types[proxy_error] = error_types.get(proxy_error, 0) + requests
    errors = load_result.errors + (requests if proxy_error is not None else 0)
    latencies = sorted(load_result.latencies_ms)
    ok_requests = max(requests - errors, 0)
    return ProxyConnectResult(
        client=spec.name,
        mode=spec.mode,
        case=case.name,
        group=case.group,
        target_scheme=case.target_scheme,
        config=case.config,
        lifecycle=case.lifecycle,
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
        errors=errors,
        warmup_errors=warmup_result.errors,
        error_types=error_types,
        warmup_error_types=warmup_result.error_types,
        measured_proxy=measured_proxy,
        total_proxy=total_proxy,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
        client_stats=client_stats,
    )


async def run_load_with_progress(
    client: AsyncProxyConnectAdapter | SyncProxyConnectAdapter,
    case: ProxyConnectCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressReporter | None,
    stage_name: str,
    mode: str,
) -> ProxyConnectLoadResult:
    if requests == 0 or not is_progress_enabled(progress):
        return await run_proxy_connect_load(client, case, url, concurrency, requests, collect=collect, mode=mode)
    with progress_stage(
        progress,
        stage_name,
        total=requests,
        milestone_percent=INNER_MILESTONE_PERCENT,
        plain_output="heartbeat",
    ) as progress_step:
        return await run_proxy_connect_load(
            client,
            case,
            url,
            concurrency,
            requests,
            collect=collect,
            mode=mode,
            progress=progress_step,
        )


async def run_proxy_connect_load(
    client: AsyncProxyConnectAdapter | SyncProxyConnectAdapter,
    case: ProxyConnectCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    mode: str,
    progress: ProgressStep | None = None,
) -> ProxyConnectLoadResult:
    if requests == 0:
        return ProxyConnectLoadResult([], 0, {})
    if mode == ASYNC_MODE:
        async_client = cast("AsyncProxyConnectAdapter", client)
        return await run_async_proxy_connect_load(
            async_client,
            case,
            url,
            concurrency,
            requests,
            collect=collect,
            progress=progress,
        )
    sync_client = cast("SyncProxyConnectAdapter", client)
    return await asyncio.to_thread(
        run_sync_proxy_connect_load,
        sync_client,
        case,
        url,
        concurrency,
        requests,
        collect=collect,
        progress=progress,
    )


async def run_async_proxy_connect_load(
    client: AsyncProxyConnectAdapter,
    case: ProxyConnectCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> ProxyConnectLoadResult:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for request_index in range(requests):
        queue.put_nowait(request_index)

    async def worker() -> ProxyConnectLoadResult:
        latencies_ms: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return ProxyConnectLoadResult(latencies_ms, sum(error_types.values()), error_types)
            started = time.perf_counter_ns()
            try:
                if not await client.request(case, url):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, requests))]
    await queue.join()
    results = await asyncio.gather(*workers)
    return merge_results(results)


def run_sync_proxy_connect_load(
    client: SyncProxyConnectAdapter,
    case: ProxyConnectCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> ProxyConnectLoadResult:
    queue: Queue[int] = Queue()
    for request_index in range(requests):
        queue.put_nowait(request_index)

    def worker() -> ProxyConnectLoadResult:
        latencies_ms: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return ProxyConnectLoadResult(latencies_ms, sum(error_types.values()), error_types)
            started = time.perf_counter_ns()
            try:
                if not client.request(case, url):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    with ThreadPoolExecutor(max_workers=min(concurrency, requests)) as executor:
        results = list(executor.map(lambda _request_index: worker(), range(min(concurrency, requests))))
    return merge_results(results)


def merge_results(results: list[ProxyConnectLoadResult]) -> ProxyConnectLoadResult:
    latencies_ms: list[float] = []
    error_types: dict[str, int] = {}
    for result in results:
        latencies_ms.extend(result.latencies_ms)
        for key, count in result.error_types.items():
            error_types[key] = error_types.get(key, 0) + count
    return ProxyConnectLoadResult(latencies_ms, sum(error_types.values()), error_types)


def proxy_delta(start: ProxyStatsDelta, end: ProxyStatsDelta) -> ProxyStatsDelta:
    return ProxyStatsDelta(
        http_requests=end.http_requests - start.http_requests,
        connect_requests=end.connect_requests - start.connect_requests,
        proxy_authorization_headers=end.proxy_authorization_headers - start.proxy_authorization_headers,
        tunnel_client_bytes=end.tunnel_client_bytes - start.tunnel_client_bytes,
        tunnel_upstream_bytes=end.tunnel_upstream_bytes - start.tunnel_upstream_bytes,
    )


def proxy_usage_error(
    *,
    case: ProxyConnectCase,
    requests: int,
    measured_proxy: ProxyStatsDelta,
    total_proxy: ProxyStatsDelta,
) -> str | None:
    if not case.uses_proxy:
        if total_proxy.http_requests == 0 and total_proxy.connect_requests == 0:
            return None
        return "unexpected_proxy_activity"
    if case.target_scheme == "http":
        if measured_proxy.http_requests >= requests:
            return None
        return "proxy_http_bypass"
    if total_proxy.connect_requests > 0:
        return None
    return "proxy_connect_bypass"


def target_url(case: ProxyConnectCase, endpoints: ProxyConnectEndpoints) -> str:
    base_url = endpoints.https_base_url if case.target_scheme == "https" else endpoints.http_base_url
    return base_url + case.path


@contextmanager
def proxy_environment(case: ProxyConnectCase, proxy_url: str) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    try:
        if case.uses_trust_env:
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            os.environ["http_proxy"] = proxy_url
            os.environ["https_proxy"] = proxy_url
            os.environ.pop("NO_PROXY", None)
            os.environ.pop("no_proxy", None)
            os.environ.pop("ALL_PROXY", None)
            os.environ.pop("all_proxy", None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def proxy_connect_progress_label(
    *,
    mode: str,
    client: str,
    case: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {case} concurrency={concurrency} repeat={repeat}/{repeats}"
