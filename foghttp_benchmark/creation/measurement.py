__all__ = (
    "client_creation_result",
    "elapsed_ms",
    "increment",
    "measure_creation_operation",
    "measure_creation_operation_sync",
)

import gc
import time

from foghttp_benchmark.creation.models import AsyncCreationOperation, SyncCreationOperation
from foghttp_benchmark.models import ClientCreationResult, ClientSpec, LoadResult
from foghttp_benchmark.resources import ResourceSnapshot, resource_delta, resource_int_delta, take_resource_snapshot
from foghttp_benchmark.runner import percentile


async def measure_creation_operation(
    spec: ClientSpec,
    *,
    scenario: str,
    client_count: int,
    iterations: int,
    repeat: int,
    operation: AsyncCreationOperation,
) -> ClientCreationResult:
    gc.collect()
    start = take_resource_snapshot()
    started = time.perf_counter()
    samples = await operation()
    duration = time.perf_counter() - started
    end = take_resource_snapshot()
    return client_creation_result(
        spec,
        scenario=scenario,
        client_count=client_count,
        iterations=iterations,
        repeat=repeat,
        duration_s=duration,
        latencies=samples.latencies_ms,
        close_latencies=samples.close_latencies_ms,
        load_result=samples.load_result,
        start=start,
        peak=samples.peak_snapshot,
        fallback_peak=end,
        end=end,
    )


def measure_creation_operation_sync(
    spec: ClientSpec,
    *,
    scenario: str,
    client_count: int,
    iterations: int,
    repeat: int,
    operation: SyncCreationOperation,
) -> ClientCreationResult:
    gc.collect()
    start = take_resource_snapshot()
    started = time.perf_counter()
    samples = operation()
    duration = time.perf_counter() - started
    end = take_resource_snapshot()
    return client_creation_result(
        spec,
        scenario=scenario,
        client_count=client_count,
        iterations=iterations,
        repeat=repeat,
        duration_s=duration,
        latencies=samples.latencies_ms,
        close_latencies=samples.close_latencies_ms,
        load_result=samples.load_result,
        start=start,
        peak=samples.peak_snapshot,
        fallback_peak=end,
        end=end,
    )


def client_creation_result(
    spec: ClientSpec,
    *,
    scenario: str,
    client_count: int,
    iterations: int,
    repeat: int,
    duration_s: float,
    latencies: list[float],
    close_latencies: list[float],
    load_result: LoadResult,
    start: ResourceSnapshot,
    peak: ResourceSnapshot | None,
    fallback_peak: ResourceSnapshot,
    end: ResourceSnapshot,
) -> ClientCreationResult:
    latencies = sorted(latencies)
    close_latencies = sorted(close_latencies)
    effective_peak = peak or fallback_peak
    return ClientCreationResult(
        client=spec.name,
        mode=spec.mode,
        scenario=scenario,
        client_count=client_count,
        iterations=iterations,
        repeat=repeat,
        duration_s=duration_s,
        operations_per_second=iterations / duration_s if duration_s > 0 else 0.0,
        p50_ms=percentile(latencies, 50),
        p90_ms=percentile(latencies, 90),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        min_ms=latencies[0] if latencies else 0.0,
        max_ms=latencies[-1] if latencies else 0.0,
        close_p50_ms=percentile(close_latencies, 50) if close_latencies else None,
        close_p95_ms=percentile(close_latencies, 95) if close_latencies else None,
        errors=load_result.errors,
        error_types=load_result.error_types,
        peak_rss_delta_mb=resource_delta(effective_peak.rss_mb, start.rss_mb),
        end_rss_delta_mb=resource_delta(end.rss_mb, start.rss_mb),
        peak_threads_delta=resource_int_delta(effective_peak.threads, start.threads),
        end_threads_delta=resource_int_delta(end.threads, start.threads),
        peak_fds_delta=resource_int_delta(effective_peak.fds, start.fds),
        end_fds_delta=resource_int_delta(end.fds, start.fds),
    )


def elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
