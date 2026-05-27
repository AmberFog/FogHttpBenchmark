__all__ = (
    "build_streaming_plan",
    "run_response_streaming_benchmarks",
)

import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
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
from foghttp_benchmark.resources import ResourceSampler
from foghttp_benchmark.runner import percentile
from foghttp_benchmark.streaming.models import (
    AsyncStreamingAdapter,
    StreamingCase,
    StreamingClientConfig,
    StreamingClientSpec,
    StreamingLoadResult,
    StreamingOutcome,
    StreamingResult,
    SyncStreamingAdapter,
)


BYTES_PER_MIB = 1024 * 1024
HTTP_OK = 200


async def run_response_streaming_benchmarks(
    *,
    clients: list[StreamingClientSpec],
    base_url: str,
    cases: list[StreamingCase],
    concurrency_levels: list[int],
    requests: int,
    warmup: int,
    repeats: int,
    shuffle: bool,
    seed: int,
    progress: ProgressReporter | None = None,
) -> list[StreamingResult]:
    plan = build_streaming_plan(
        clients=clients,
        cases=cases,
        concurrency_levels=concurrency_levels,
        repeats=repeats,
        shuffle=shuffle,
        seed=seed,
    )
    results: list[StreamingResult] = []
    with progress_stage(progress, "Response streaming runs", total=len(plan)) as progress_step:
        for case, concurrency, spec, repeat in plan:
            label = streaming_progress_label(
                mode=spec.mode,
                client=spec.name,
                case=case.name,
                concurrency=concurrency,
                repeat=repeat,
                repeats=repeats,
            )
            progress_step.update(label)
            result = await run_streaming_case(
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
    return results


def build_streaming_plan(
    *,
    clients: list[StreamingClientSpec],
    cases: list[StreamingCase],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[StreamingCase, int, StreamingClientSpec, int]]:
    plan: list[tuple[StreamingCase, int, StreamingClientSpec, int]] = []
    for case in cases:
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((case, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def run_streaming_case(
    *,
    spec: StreamingClientSpec,
    base_url: str,
    case: StreamingCase,
    concurrency: int,
    requests: int,
    warmup: int,
    repeat: int,
    progress: ProgressReporter | None = None,
    progress_label: str | None = None,
) -> StreamingResult:
    config = StreamingClientConfig(concurrency=concurrency, request_limit=concurrency)
    client = spec.factory(config)
    url = base_url + case.path
    label = progress_label or f"{spec.mode}/{spec.name} {case.name} concurrency={concurrency} repeat={repeat}"
    try:
        warmup_result = await run_load_with_progress(
            client,
            case,
            url,
            concurrency,
            warmup,
            collect=False,
            progress=progress,
            stage_name=f"Warmup streaming load: {label}",
            mode=spec.mode,
        )
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
                stage_name=f"Measured streaming load: {label}",
                mode=spec.mode,
            )
        duration = time.perf_counter() - started
        client_stats = client.stats()
    finally:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

    latencies = sorted(load_result.latencies_ms)
    first_chunk_latencies = sorted(load_result.first_chunk_latencies_ms)
    ok_streams = requests - load_result.errors
    return StreamingResult(
        client=spec.name,
        mode=spec.mode,
        case=case.name,
        read=case.read,
        consume=case.consume,
        concurrency=concurrency,
        request_limit=concurrency,
        requests=requests,
        repeat=repeat,
        duration_s=duration,
        streams_per_second=requests / duration if duration > 0 else 0.0,
        ok_streams_per_second=ok_streams / duration if duration > 0 else 0.0,
        ok_streams=ok_streams,
        bytes_read_total=load_result.bytes_read,
        mb_per_second=(load_result.bytes_read / BYTES_PER_MIB) / duration if duration > 0 else 0.0,
        chunks_read_total=load_result.chunks_read,
        text_chars_read_total=load_result.text_chars_read,
        lines_read_total=load_result.lines_read,
        lines_per_second=load_result.lines_read / duration if duration > 0 else 0.0,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        first_chunk_p50_ms=optional_percentile(first_chunk_latencies, 50),
        first_chunk_p95_ms=optional_percentile(first_chunk_latencies, 95),
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
    client: AsyncStreamingAdapter | SyncStreamingAdapter,
    case: StreamingCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressReporter | None,
    stage_name: str,
    mode: str,
) -> StreamingLoadResult:
    if requests == 0 or not is_progress_enabled(progress):
        return await run_streaming_load(client, case, url, concurrency, requests, collect=collect, mode=mode)
    with progress_stage(
        progress,
        stage_name,
        total=requests,
        milestone_percent=INNER_MILESTONE_PERCENT,
        plain_output="heartbeat",
    ) as progress_step:
        return await run_streaming_load(
            client,
            case,
            url,
            concurrency,
            requests,
            collect=collect,
            mode=mode,
            progress=progress_step,
        )


async def run_streaming_load(
    client: AsyncStreamingAdapter | SyncStreamingAdapter,
    case: StreamingCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    mode: str,
    progress: ProgressStep | None = None,
) -> StreamingLoadResult:
    if requests == 0:
        return StreamingLoadResult([], [], 0, 0, 0, 0, 0, {})
    if mode == ASYNC_MODE:
        async_client = cast("AsyncStreamingAdapter", client)
        return await run_async_streaming_load(
            async_client,
            case,
            url,
            concurrency,
            requests,
            collect=collect,
            progress=progress,
        )
    sync_client = cast("SyncStreamingAdapter", client)
    return await asyncio.to_thread(
        run_sync_streaming_load,
        sync_client,
        case,
        url,
        concurrency,
        requests,
        collect=collect,
        progress=progress,
    )


async def run_async_streaming_load(
    client: AsyncStreamingAdapter,
    case: StreamingCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> StreamingLoadResult:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for request_index in range(requests):
        queue.put_nowait(request_index)

    async def worker() -> StreamingLoadResult:
        latencies_ms: list[float] = []
        first_chunk_latencies_ms: list[float] = []
        bytes_read = 0
        chunks_read = 0
        text_chars_read = 0
        lines_read = 0
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return StreamingLoadResult(
                    latencies_ms,
                    first_chunk_latencies_ms,
                    bytes_read,
                    chunks_read,
                    text_chars_read,
                    lines_read,
                    sum(error_types.values()),
                    error_types,
                )

            started_ns = time.perf_counter_ns()
            try:
                outcome = await client.stream(case, url)
                if not outcome_matches(case, outcome):
                    increment(error_types, "check_failed")
                bytes_read += outcome.bytes_read
                chunks_read += outcome.chunks_read
                text_chars_read += outcome.text_chars_read
                lines_read += outcome.lines_read
                if outcome.first_chunk_ms is not None:
                    first_chunk_latencies_ms.append(outcome.first_chunk_ms)
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    workers = [asyncio.create_task(worker()) for _worker_index in range(min(concurrency, requests))]
    await queue.join()
    results = await asyncio.gather(*workers)
    return merge_streaming_results(results)


def run_sync_streaming_load(
    client: SyncStreamingAdapter,
    case: StreamingCase,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
    progress: ProgressStep | None = None,
) -> StreamingLoadResult:
    queue: Queue[int] = Queue()
    for request_index in range(requests):
        queue.put_nowait(request_index)

    def worker() -> StreamingLoadResult:
        latencies_ms: list[float] = []
        first_chunk_latencies_ms: list[float] = []
        bytes_read = 0
        chunks_read = 0
        text_chars_read = 0
        lines_read = 0
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return StreamingLoadResult(
                    latencies_ms,
                    first_chunk_latencies_ms,
                    bytes_read,
                    chunks_read,
                    text_chars_read,
                    lines_read,
                    sum(error_types.values()),
                    error_types,
                )

            started_ns = time.perf_counter_ns()
            try:
                outcome = client.stream(case, url)
                if not outcome_matches(case, outcome):
                    increment(error_types, "check_failed")
                bytes_read += outcome.bytes_read
                chunks_read += outcome.chunks_read
                text_chars_read += outcome.text_chars_read
                lines_read += outcome.lines_read
                if outcome.first_chunk_ms is not None:
                    first_chunk_latencies_ms.append(outcome.first_chunk_ms)
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
                queue.task_done()
                if progress is not None:
                    progress.advance()

    with ThreadPoolExecutor(max_workers=min(concurrency, requests)) as executor:
        results = list(executor.map(lambda _worker_index: worker(), range(min(concurrency, requests))))
    return merge_streaming_results(results)


def outcome_matches(case: StreamingCase, outcome: StreamingOutcome) -> bool:
    if outcome.status_code != HTTP_OK:
        return False
    if outcome.chunks_read < 1 or outcome.bytes_read < 1:
        return False
    if case.read == "lines":
        return _line_outcome_matches(case, outcome)
    if case.consume == "first-chunk":
        return outcome.bytes_read <= case.size_bytes
    return outcome.bytes_read == case.size_bytes


def _line_outcome_matches(case: StreamingCase, outcome: StreamingOutcome) -> bool:
    if outcome.lines_read < 1:
        return False
    if case.consume == "first-line":
        return outcome.lines_read == 1 and outcome.bytes_read <= case.size_bytes
    if case.expected_lines is not None and outcome.lines_read != case.expected_lines:
        return False
    return outcome.bytes_read == case.size_bytes


def merge_streaming_results(results: list[StreamingLoadResult]) -> StreamingLoadResult:
    latencies_ms: list[float] = []
    first_chunk_latencies_ms: list[float] = []
    bytes_read = 0
    chunks_read = 0
    text_chars_read = 0
    lines_read = 0
    error_types: dict[str, int] = {}
    for result in results:
        latencies_ms.extend(result.latencies_ms)
        first_chunk_latencies_ms.extend(result.first_chunk_latencies_ms)
        bytes_read += result.bytes_read
        chunks_read += result.chunks_read
        text_chars_read += result.text_chars_read
        lines_read += result.lines_read
        for key, count in result.error_types.items():
            error_types[key] = error_types.get(key, 0) + count
    return StreamingLoadResult(
        latencies_ms,
        first_chunk_latencies_ms,
        bytes_read,
        chunks_read,
        text_chars_read,
        lines_read,
        sum(error_types.values()),
        error_types,
    )


def optional_percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    return percentile(values, percent)


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def streaming_progress_label(
    *,
    mode: str,
    client: str,
    case: str,
    concurrency: int,
    repeat: int,
    repeats: int,
) -> str:
    return f"{mode}/{client} {case} concurrency={concurrency} repeat={repeat}/{repeats}"
