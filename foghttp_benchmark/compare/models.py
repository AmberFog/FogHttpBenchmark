__all__ = (
    "BenchmarkReport",
    "BenchmarkRow",
    "BenchmarkSuite",
    "ComparisonMetadata",
    "ComparisonResult",
    "ComparisonValidity",
    "ErrorRow",
    "JsonObject",
    "ResourceSummary",
    "RowComparison",
    "SegmentSummary",
    "WinsComparison",
)

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from foghttp_benchmark.validity.models import ValiditySummary


JsonObject: TypeAlias = dict[str, object]
BenchmarkSuite: TypeAlias = Literal[
    "requests",
    "client-creation",
    "resource-backpressure",
    "one-upstream",
    "request-builder",
    "compressed-response",
    "response-streaming",
    "proxy-connect",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    path: Path
    suite: BenchmarkSuite
    timestamp: str
    package_versions: dict[str, str]
    rows: list["BenchmarkRow"]
    aggregate_rows: list[JsonObject]
    metadata: JsonObject
    validity: ValiditySummary


@dataclass(frozen=True, slots=True)
class BenchmarkRow:
    suite: BenchmarkSuite
    identity: tuple[str, ...]
    group: tuple[str, ...]
    label: str
    mode: str
    client: str
    scenario: str
    primary_value: float
    p95_ms: float | None
    p99_ms: float | None
    errors_total: int
    warmup_errors_total: int
    error_rate_percent: float | None
    rss_mb: float | None
    threads: int | None
    fds: int | None


@dataclass(frozen=True, slots=True)
class ComparisonMetadata:
    old_path: Path
    new_path: Path
    suite: BenchmarkSuite
    focus_client: str
    old_timestamp: str
    new_timestamp: str
    old_focus_version: str
    new_focus_version: str


@dataclass(frozen=True, slots=True)
class ComparisonValidity:
    old_status: str
    new_status: str
    blocks_strong_conclusions: bool
    old_reason_count: int
    new_reason_count: int
    old_reasons: tuple[str, ...]
    new_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    name: str
    rows: int
    primary_geomean_ratio: float | None
    primary_median_ratio: float | None
    p95_geomean_ratio: float | None
    p99_geomean_ratio: float | None


@dataclass(frozen=True, slots=True)
class RowComparison:
    row: BenchmarkRow
    old_primary: float
    new_primary: float
    primary_ratio: float
    old_p95_ms: float | None
    new_p95_ms: float | None
    p95_ratio: float | None
    old_p99_ms: float | None
    new_p99_ms: float | None
    p99_ratio: float | None
    old_errors_total: int
    new_errors_total: int
    old_error_rate_percent: float | None
    new_error_rate_percent: float | None


@dataclass(frozen=True, slots=True)
class ErrorRow:
    label: str
    mode: str
    client: str
    scenario: str
    errors_total: int
    warmup_errors_total: int
    error_rate_percent: float | None


@dataclass(frozen=True, slots=True)
class WinsComparison:
    old_wins: int
    new_wins: int
    comparable_groups: int
    old_geomean_to_winner: float | None
    new_geomean_to_winner: float | None
    old_average_rank: float | None
    new_average_rank: float | None


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    old_rss_mb_max: float | None
    new_rss_mb_max: float | None
    old_threads_max: int | None
    new_threads_max: int | None
    old_fds_max: int | None
    new_fds_max: int | None
    old_errors_total: int
    new_errors_total: int


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    metadata: ComparisonMetadata
    validity: ComparisonValidity
    overall: SegmentSummary
    by_mode: list[SegmentSummary]
    by_scenario: list[SegmentSummary]
    wins: WinsComparison | None
    top_improvements: list[RowComparison]
    top_regressions: list[RowComparison]
    new_error_rows: list[ErrorRow]
    resource_summary: ResourceSummary
    unmatched_old_rows: int
    unmatched_new_rows: int
