__all__ = (
    "AsyncCreationOperation",
    "CreationPlanItem",
    "CreationSamples",
    "SyncCreationOperation",
)

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias

from foghttp_benchmark.models import ClientSpec, LoadResult
from foghttp_benchmark.resources import ResourceSnapshot


@dataclass(frozen=True)
class CreationSamples:
    latencies_ms: list[float]
    close_latencies_ms: list[float]
    load_result: LoadResult
    peak_snapshot: ResourceSnapshot | None = None


AsyncCreationOperation: TypeAlias = Callable[[], Awaitable[CreationSamples]]
SyncCreationOperation: TypeAlias = Callable[[], CreationSamples]
CreationPlanItem: TypeAlias = tuple[ClientSpec, int, int, str]
