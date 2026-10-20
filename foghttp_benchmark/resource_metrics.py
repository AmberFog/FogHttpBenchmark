__all__ = (
    "RESOURCE_METRIC_SCHEMA_VERSION",
    "ResourceCoverage",
    "ResourceMetricCoverage",
    "optional_resource_max",
    "resource_coverage",
)

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
from typing import TypeAlias, TypeVar


RESOURCE_METRIC_SCHEMA_VERSION = 2
ResourceNumber = TypeVar("ResourceNumber", int, float)


@dataclass(frozen=True, slots=True)
class ResourceMetricCoverage:
    available: int
    expected: int
    unavailable_reasons: tuple[str, ...] = ()


ResourceCoverage: TypeAlias = dict[str, ResourceMetricCoverage]


def optional_resource_max(values: Iterable[ResourceNumber | None]) -> ResourceNumber | None:
    present = resource_values(values)
    return max(present) if present else None


def resource_coverage(fields: Mapping[str, Iterable[int | float | None]]) -> ResourceCoverage:
    coverage: ResourceCoverage = {}
    for name, observations in fields.items():
        values = list(observations)
        available = len(resource_values(values))
        coverage[name] = ResourceMetricCoverage(
            available=available,
            expected=len(values),
            unavailable_reasons=("reason-not-recorded",) if available < len(values) else (),
        )
    return coverage


def resource_values(values: Iterable[ResourceNumber | None]) -> list[ResourceNumber]:
    present: list[ResourceNumber] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = "Resource measurements must be numeric or null; bool is not a measurement"
            raise TypeError(msg)
        if isinstance(value, float) and not math.isfinite(value):
            msg = "Resource measurements must be finite or null"
            raise ValueError(msg)
        present.append(value)
    return present
