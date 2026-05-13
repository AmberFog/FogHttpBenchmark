__all__ = (
    "run_async_create_close",
    "run_async_create_first_request",
    "run_async_many_clients",
    "run_async_reused_request",
)

import time
from typing import TYPE_CHECKING

from foghttp_benchmark.creation.client_io import close_async_client, create_async_client
from foghttp_benchmark.creation.constants import (
    CREATE_CLOSE_SCENARIO,
    CREATE_FIRST_REQUEST_SCENARIO,
    MANY_CLIENTS_SCENARIO,
    REUSED_REQUEST_SCENARIO,
)
from foghttp_benchmark.creation.measurement import elapsed_ms, increment, measure_creation_operation
from foghttp_benchmark.creation.models import CreationSamples
from foghttp_benchmark.load import outcome_matches
from foghttp_benchmark.models import ClientConfig, ClientCreationResult, ClientSpec, LoadResult, Scenario
from foghttp_benchmark.resources import ResourceSnapshot, take_resource_snapshot


if TYPE_CHECKING:
    from foghttp_benchmark.clients.base import AsyncClientAdapter


async def run_async_create_close(
    spec: ClientSpec,
    config: ClientConfig,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    async def operation() -> CreationSamples:
        latencies: list[float] = []
        close_latencies: list[float] = []
        errors: dict[str, int] = {}
        peak_snapshot: ResourceSnapshot | None = None
        for _ in range(iterations):
            started = time.perf_counter_ns()
            try:
                client = create_async_client(spec, config)
                peak_snapshot = take_resource_snapshot()
                close_started = time.perf_counter_ns()
                await close_async_client(client)
                close_latencies.append(elapsed_ms(close_started))
            except Exception as exc:  # noqa: BLE001
                increment(errors, type(exc).__name__)
            finally:
                latencies.append(elapsed_ms(started))
        return CreationSamples(latencies, close_latencies, LoadResult([], sum(errors.values()), errors), peak_snapshot)

    return await measure_creation_operation(
        spec,
        scenario=CREATE_CLOSE_SCENARIO,
        client_count=1,
        iterations=iterations,
        repeat=repeat,
        operation=operation,
    )


async def run_async_create_first_request(
    spec: ClientSpec,
    config: ClientConfig,
    scenario: Scenario,
    url: str,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    async def operation() -> CreationSamples:
        latencies: list[float] = []
        close_latencies: list[float] = []
        errors: dict[str, int] = {}
        peak_snapshot: ResourceSnapshot | None = None
        for _ in range(iterations):
            client: AsyncClientAdapter | None = None
            started = time.perf_counter_ns()
            try:
                client = create_async_client(spec, config)
                outcome = await client.request(scenario, url)
                if not outcome_matches(scenario, outcome):
                    increment(errors, "check_failed")
                peak_snapshot = take_resource_snapshot()
            except Exception as exc:  # noqa: BLE001
                increment(errors, type(exc).__name__)
            finally:
                if client is not None:
                    close_started = time.perf_counter_ns()
                    try:
                        await close_async_client(client)
                    except Exception as exc:  # noqa: BLE001
                        increment(errors, f"close_{type(exc).__name__}")
                    close_latencies.append(elapsed_ms(close_started))
                latencies.append(elapsed_ms(started))
        return CreationSamples(latencies, close_latencies, LoadResult([], sum(errors.values()), errors), peak_snapshot)

    return await measure_creation_operation(
        spec,
        scenario=CREATE_FIRST_REQUEST_SCENARIO,
        client_count=1,
        iterations=iterations,
        repeat=repeat,
        operation=operation,
    )


async def run_async_reused_request(
    spec: ClientSpec,
    config: ClientConfig,
    scenario: Scenario,
    url: str,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    async def operation() -> CreationSamples:
        latencies: list[float] = []
        close_latencies: list[float] = []
        errors: dict[str, int] = {}
        peak_snapshot: ResourceSnapshot | None = None
        client: AsyncClientAdapter | None = None
        try:
            client = create_async_client(spec, config)
            await client.request(scenario, url)
            for _ in range(iterations):
                started = time.perf_counter_ns()
                outcome = await client.request(scenario, url)
                if not outcome_matches(scenario, outcome):
                    increment(errors, "check_failed")
                latencies.append(elapsed_ms(started))
            peak_snapshot = take_resource_snapshot()
        except Exception as exc:  # noqa: BLE001
            increment(errors, type(exc).__name__)
        finally:
            if client is not None:
                close_started = time.perf_counter_ns()
                try:
                    await close_async_client(client)
                except Exception as exc:  # noqa: BLE001
                    increment(errors, f"close_{type(exc).__name__}")
                close_latencies.append(elapsed_ms(close_started))
        return CreationSamples(latencies, close_latencies, LoadResult([], sum(errors.values()), errors), peak_snapshot)

    return await measure_creation_operation(
        spec,
        scenario=REUSED_REQUEST_SCENARIO,
        client_count=1,
        iterations=iterations,
        repeat=repeat,
        operation=operation,
    )


async def run_async_many_clients(
    spec: ClientSpec,
    config: ClientConfig,
    client_count: int,
    repeat: int,
) -> ClientCreationResult:
    async def operation() -> CreationSamples:
        create_latencies: list[float] = []
        close_latencies: list[float] = []
        clients: list[AsyncClientAdapter] = []
        errors: dict[str, int] = {}
        peak_snapshot: ResourceSnapshot | None = None
        try:
            for _ in range(client_count):
                started = time.perf_counter_ns()
                clients.append(create_async_client(spec, config))
                create_latencies.append(elapsed_ms(started))
            peak_snapshot = take_resource_snapshot()
        except Exception as exc:  # noqa: BLE001
            increment(errors, type(exc).__name__)
        finally:
            for client in clients:
                close_started = time.perf_counter_ns()
                try:
                    await close_async_client(client)
                except Exception as exc:  # noqa: BLE001
                    increment(errors, f"close_{type(exc).__name__}")
                close_latencies.append(elapsed_ms(close_started))
        return CreationSamples(
            create_latencies,
            close_latencies,
            LoadResult([], sum(errors.values()), errors),
            peak_snapshot,
        )

    return await measure_creation_operation(
        spec,
        scenario=MANY_CLIENTS_SCENARIO,
        client_count=client_count,
        iterations=client_count,
        repeat=repeat,
        operation=operation,
    )
