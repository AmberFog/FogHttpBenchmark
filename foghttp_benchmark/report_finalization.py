__all__ = ("MergedReportFinalizer", "MergedSuiteReport", "preserve_merged_report")

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from foghttp_benchmark.models import JsonObject


@dataclass(frozen=True, slots=True)
class MergedSuiteReport:
    aggregate_rows: list[JsonObject]
    metadata: JsonObject


MergedReportFinalizer: TypeAlias = Callable[[list[JsonObject], list[JsonObject]], MergedSuiteReport]


def preserve_merged_report(rows: list[JsonObject], _children_metadata: list[JsonObject]) -> MergedSuiteReport:
    return MergedSuiteReport(rows, {})
