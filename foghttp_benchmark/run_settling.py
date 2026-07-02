__all__ = (
    "DEFAULT_RUN_COOLDOWN_OPENED_THRESHOLD",
    "DEFAULT_RUN_COOLDOWN_S",
    "RUN_COOLDOWN_ENV",
    "RUN_COOLDOWN_OPENED_THRESHOLD_ENV",
    "RunSettlingConfig",
    "run_settling_config",
    "settle_after_run",
    "should_settle_after_run",
)

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from foghttp_benchmark.models import ClientStatKey, ClientStats
from foghttp_benchmark.progress import ProgressReporter, progress_status


RUN_COOLDOWN_ENV = "FOGHTTP_BENCHMARK_RUN_COOLDOWN_S"
RUN_COOLDOWN_OPENED_THRESHOLD_ENV = "FOGHTTP_BENCHMARK_RUN_COOLDOWN_OPENED_THRESHOLD"
DEFAULT_RUN_COOLDOWN_S = 3.0
DEFAULT_RUN_COOLDOWN_OPENED_THRESHOLD = 256


@dataclass(frozen=True, slots=True)
class RunSettlingConfig:
    cooldown_s: float
    opened_connection_threshold: int


def run_settling_config(env: Mapping[str, str]) -> RunSettlingConfig:
    return RunSettlingConfig(
        cooldown_s=positive_float(
            env,
            name=RUN_COOLDOWN_ENV,
            default=DEFAULT_RUN_COOLDOWN_S,
        ),
        opened_connection_threshold=positive_int(
            env,
            name=RUN_COOLDOWN_OPENED_THRESHOLD_ENV,
            default=DEFAULT_RUN_COOLDOWN_OPENED_THRESHOLD,
        ),
    )


async def settle_after_run(
    stats: ClientStats | None,
    config: RunSettlingConfig,
    *,
    progress: ProgressReporter | None = None,
) -> None:
    if not should_settle_after_run(stats, config):
        return

    opened_connections = int_stat(stats, "connections_opened")
    failed_connections = int_stat(stats, "connections_open_failed")
    progress_status(
        progress,
        (
            f"Waiting {config.cooldown_s:.1f}s after TCP churn "
            f"(opened={opened_connections}, open_failed={failed_connections})"
        ),
    )
    await asyncio.sleep(config.cooldown_s)


def should_settle_after_run(stats: ClientStats | None, config: RunSettlingConfig) -> bool:
    opened_connections = int_stat(stats, "connections_opened")
    failed_connections = int_stat(stats, "connections_open_failed")
    return failed_connections > 0 or opened_connections >= config.opened_connection_threshold


def int_stat(stats: ClientStats | None, key: ClientStatKey) -> int:
    if stats is None:
        return 0
    value = stats.get(key)
    return value if isinstance(value, int) else 0


def positive_float(env: Mapping[str, str], *, name: str, default: float) -> float:
    raw_value = env.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        msg = f"{name} must be a positive float"
        raise ValueError(msg) from exc
    if value <= 0:
        msg = f"{name} must be a positive float"
        raise ValueError(msg)
    return value


def positive_int(env: Mapping[str, str], *, name: str, default: int) -> int:
    raw_value = env.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        msg = f"{name} must be a positive integer"
        raise ValueError(msg) from exc
    if value <= 0:
        msg = f"{name} must be a positive integer"
        raise ValueError(msg)
    return value
