__all__ = ("run_client_creation_benchmarks",)

import asyncio
import random

from foghttp_benchmark.constants import DEFAULT_MAX_REDIRECTS, SYNC_MODE
from foghttp_benchmark.creation.constants import (
    CREATE_CLOSE_SCENARIO,
    CREATE_FIRST_REQUEST_SCENARIO,
    MANY_CLIENTS_SCENARIO,
    REUSED_REQUEST_SCENARIO,
    SINGLE_CLIENT_SCENARIOS,
)
from foghttp_benchmark.creation.models import CreationPlanItem
from foghttp_benchmark.creation.operations_async import (
    run_async_create_close,
    run_async_create_first_request,
    run_async_many_clients,
    run_async_reused_request,
)
from foghttp_benchmark.creation.operations_sync import (
    run_sync_create_close,
    run_sync_create_first_request,
    run_sync_many_clients,
    run_sync_reused_request,
)
from foghttp_benchmark.models import ClientConfig, ClientCreationResult, ClientSpec, Scenario


async def run_client_creation_benchmarks(
    *,
    clients: list[ClientSpec],
    base_url: str,
    scenario: Scenario,
    iterations: int,
    repeats: int,
    client_counts: list[int],
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    shuffle: bool,
    seed: int,
) -> list[ClientCreationResult]:
    plan = build_creation_plan(clients, repeats, client_counts, shuffle=shuffle, seed=seed)
    url = base_url + scenario.path
    results: list[ClientCreationResult] = []
    for spec, repeat, client_count, scenario_name in plan:
        config = ClientConfig(
            concurrency=1,
            max_connections=1,
            follow_redirects=False,
            max_redirects=max_redirects,
        )
        result = await measure_creation_scenario(
            spec,
            config,
            scenario_name=scenario_name,
            scenario=scenario,
            url=url,
            iterations=iterations,
            client_count=client_count,
            repeat=repeat,
        )
        results.append(result)
    return results


def build_creation_plan(
    clients: list[ClientSpec],
    repeats: int,
    client_counts: list[int],
    *,
    shuffle: bool,
    seed: int,
) -> list[CreationPlanItem]:
    plan: list[CreationPlanItem] = []
    for spec in clients:
        for repeat in range(1, repeats + 1):
            plan.extend((spec, repeat, 1, scenario) for scenario in SINGLE_CLIENT_SCENARIOS)
            plan.extend((spec, repeat, client_count, MANY_CLIENTS_SCENARIO) for client_count in client_counts)
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def measure_creation_scenario(
    spec: ClientSpec,
    config: ClientConfig,
    *,
    scenario_name: str,
    scenario: Scenario,
    url: str,
    iterations: int,
    client_count: int,
    repeat: int,
) -> ClientCreationResult:
    if scenario_name == CREATE_CLOSE_SCENARIO:
        return await measure_create_close(spec, config, iterations=iterations, repeat=repeat)
    if scenario_name == CREATE_FIRST_REQUEST_SCENARIO:
        return await measure_create_first_request(spec, config, scenario, url, iterations=iterations, repeat=repeat)
    if scenario_name == REUSED_REQUEST_SCENARIO:
        return await measure_reused_request(spec, config, scenario, url, iterations=iterations, repeat=repeat)
    return await measure_many_clients(spec, config, client_count=client_count, repeat=repeat)


async def measure_create_close(
    spec: ClientSpec,
    config: ClientConfig,
    *,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    if spec.mode == SYNC_MODE:
        return await asyncio.to_thread(run_sync_create_close, spec, config, iterations, repeat)
    return await run_async_create_close(spec, config, iterations, repeat)


async def measure_create_first_request(
    spec: ClientSpec,
    config: ClientConfig,
    scenario: Scenario,
    url: str,
    *,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    if spec.mode == SYNC_MODE:
        return await asyncio.to_thread(run_sync_create_first_request, spec, config, scenario, url, iterations, repeat)
    return await run_async_create_first_request(spec, config, scenario, url, iterations, repeat)


async def measure_reused_request(
    spec: ClientSpec,
    config: ClientConfig,
    scenario: Scenario,
    url: str,
    *,
    iterations: int,
    repeat: int,
) -> ClientCreationResult:
    if spec.mode == SYNC_MODE:
        return await asyncio.to_thread(run_sync_reused_request, spec, config, scenario, url, iterations, repeat)
    return await run_async_reused_request(spec, config, scenario, url, iterations, repeat)


async def measure_many_clients(
    spec: ClientSpec,
    config: ClientConfig,
    *,
    client_count: int,
    repeat: int,
) -> ClientCreationResult:
    if spec.mode == SYNC_MODE:
        return await asyncio.to_thread(run_sync_many_clients, spec, config, client_count, repeat)
    return await run_async_many_clients(spec, config, client_count, repeat)
