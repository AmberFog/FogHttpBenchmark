__all__ = (
    "client_stat_max",
    "client_stat_values",
    "error_rate",
    "median_metric",
    "optional_max",
    "sum_metric",
)

from collections.abc import Callable, Iterable, Sequence
import statistics
from typing import TypeVar

from foghttp_benchmark.models import ClientStatKey, ResourceBackpressureResult
from foghttp_benchmark.resource_metrics import optional_resource_max


OptionalMaxValue = TypeVar("OptionalMaxValue", int, float)


def sum_metric(
    results: Sequence[ResourceBackpressureResult],
    metric: Callable[[ResourceBackpressureResult], int],
) -> int:
    return sum(metric(result) for result in results)


def median_metric(
    results: Sequence[ResourceBackpressureResult],
    metric: Callable[[ResourceBackpressureResult], float],
) -> float:
    return statistics.median(metric(result) for result in results)


def error_rate(errors: int, requests: int) -> float:
    if requests == 0:
        return 0.0
    return (errors / requests) * 100


def optional_max(values: Iterable[OptionalMaxValue | None]) -> OptionalMaxValue | None:
    return optional_resource_max(values)


def client_stat_max(results: Sequence[ResourceBackpressureResult], key: ClientStatKey) -> int | None:
    return optional_resource_max(client_stat_values(results, key))


def client_stat_values(results: Sequence[ResourceBackpressureResult], key: ClientStatKey) -> list[int | None]:
    return [result.client_stats.get(key) if result.client_stats is not None else None for result in results]
