__all__ = (
    "client_stat_max",
    "coefficient_of_variation",
    "error_rate",
    "median_metric",
    "merge_error_types",
    "optional_max",
    "sum_metric",
)

from collections.abc import Callable, Iterable, Sequence
import statistics
from typing import TypeVar

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES
from foghttp_benchmark.models import ClientStatKey, ResourceBackpressureResult


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


def coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def optional_max(values: Iterable[OptionalMaxValue | None]) -> OptionalMaxValue | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def client_stat_max(results: Sequence[ResourceBackpressureResult], key: ClientStatKey) -> int | None:
    values: list[int] = []
    for result in results:
        if result.client_stats is None:
            continue
        value = result.client_stats.get(key)
        if isinstance(value, int):
            values.append(value)
    return max(values) if values else None


def merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for errors in values:
        for key, count in errors.items():
            merged[key] = merged.get(key, 0) + count
    return merged
