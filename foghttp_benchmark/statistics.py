__all__ = ("coefficient_of_variation", "merge_error_types", "percentile")

from collections.abc import Iterable, Sequence
import statistics

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES


def coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
    return values[index]


def merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for error_types in values:
        for name, count in error_types.items():
            merged[name] = merged.get(name, 0) + count
    return merged
