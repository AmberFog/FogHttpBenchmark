__all__ = ("compare_reports",)

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
import statistics

from foghttp_benchmark.compare.models import (
    BenchmarkReport,
    BenchmarkRow,
    ComparisonMetadata,
    ComparisonResult,
    ComparisonValidity,
    ErrorRow,
    ResourceSummary,
    RowComparison,
    SegmentSummary,
    WinsComparison,
)
from foghttp_benchmark.validity.models import ValidityReason


@dataclass(frozen=True, slots=True)
class WinsSnapshot:
    wins: int
    groups: int
    ratios_to_winner: list[float]
    ranks: list[float]


def compare_reports(
    old_report: BenchmarkReport,
    new_report: BenchmarkReport,
    *,
    focus_client: str,
    top_n: int,
) -> ComparisonResult:
    validate_comparable_reports(old_report, new_report)
    old_rows = focus_rows_by_identity(old_report, focus_client)
    new_rows = focus_rows_by_identity(new_report, focus_client)
    shared_keys = sorted(set(old_rows) & set(new_rows))
    if not shared_keys:
        msg = f"No comparable rows found for focus client {focus_client!r}"
        raise ValueError(msg)

    comparisons = [compare_row(old_rows[key], new_rows[key]) for key in shared_keys]
    return ComparisonResult(
        metadata=ComparisonMetadata(
            old_path=old_report.path,
            new_path=new_report.path,
            suite=new_report.suite,
            focus_client=focus_client,
            old_timestamp=old_report.timestamp,
            new_timestamp=new_report.timestamp,
            old_focus_version=old_report.package_versions.get(focus_client, "-"),
            new_focus_version=new_report.package_versions.get(focus_client, "-"),
        ),
        validity=comparison_validity(old_report, new_report),
        overall=summarize_segment("overall", comparisons),
        by_mode=summarize_by(lambda item: item.row.mode, comparisons),
        by_scenario=summarize_by(lambda item: item.row.scenario, comparisons),
        wins=None
        if blocks_strong_conclusions(old_report, new_report)
        else compare_wins(old_report, new_report, focus_client),
        top_improvements=sorted(comparisons, key=lambda item: item.primary_ratio, reverse=True)[:top_n],
        top_regressions=sorted(comparisons, key=lambda item: item.primary_ratio)[:top_n],
        new_error_rows=error_rows(new_report),
        resource_summary=resource_summary(old_rows.values(), new_rows.values()),
        unmatched_old_rows=len(set(old_rows) - set(new_rows)),
        unmatched_new_rows=len(set(new_rows) - set(old_rows)),
    )


def validate_comparable_reports(old_report: BenchmarkReport, new_report: BenchmarkReport) -> None:
    if old_report.suite == "unknown" or new_report.suite == "unknown":
        msg = "Benchmark suite could not be inferred for one of the reports"
        raise ValueError(msg)
    if old_report.suite != new_report.suite:
        msg = f"Reports must use the same benchmark suite: old={old_report.suite}, new={new_report.suite}"
        raise ValueError(msg)


def comparison_validity(old_report: BenchmarkReport, new_report: BenchmarkReport) -> ComparisonValidity:
    return ComparisonValidity(
        old_status=old_report.validity.status,
        new_status=new_report.validity.status,
        blocks_strong_conclusions=blocks_strong_conclusions(old_report, new_report),
        old_reason_count=old_report.validity.reason_count,
        new_reason_count=new_report.validity.reason_count,
        old_reasons=tuple(reason_summary(reason) for reason in old_report.validity.reasons),
        new_reasons=tuple(reason_summary(reason) for reason in new_report.validity.reasons),
    )


def blocks_strong_conclusions(old_report: BenchmarkReport, new_report: BenchmarkReport) -> bool:
    return not old_report.validity.can_compare or not new_report.validity.can_compare


def reason_summary(reason: ValidityReason) -> str:
    return f"{reason.status}:{reason.code}:{reason.row_label}"


def focus_rows_by_identity(report: BenchmarkReport, focus_client: str) -> dict[tuple[str, ...], BenchmarkRow]:
    return {row.identity: row for row in report.rows if row.client == focus_client}


def compare_row(old_row: BenchmarkRow, new_row: BenchmarkRow) -> RowComparison:
    return RowComparison(
        row=new_row,
        old_primary=old_row.primary_value,
        new_primary=new_row.primary_value,
        primary_ratio=safe_ratio(new_row.primary_value, old_row.primary_value),
        old_p95_ms=old_row.p95_ms,
        new_p95_ms=new_row.p95_ms,
        p95_ratio=optional_ratio(new_row.p95_ms, old_row.p95_ms),
        old_p99_ms=old_row.p99_ms,
        new_p99_ms=new_row.p99_ms,
        p99_ratio=optional_ratio(new_row.p99_ms, old_row.p99_ms),
        old_errors_total=old_row.errors_total,
        new_errors_total=new_row.errors_total,
        old_error_rate_percent=old_row.error_rate_percent,
        new_error_rate_percent=new_row.error_rate_percent,
    )


def summarize_by(
    segment_name: Callable[[RowComparison], str],
    comparisons: list[RowComparison],
) -> list[SegmentSummary]:
    grouped: dict[str, list[RowComparison]] = defaultdict(list)
    for comparison in comparisons:
        grouped[segment_name(comparison)].append(comparison)
    return [summarize_segment(name, items) for name, items in sorted(grouped.items())]


def summarize_segment(name: str, comparisons: list[RowComparison]) -> SegmentSummary:
    primary_ratios = [item.primary_ratio for item in comparisons]
    p95_ratios = [item.p95_ratio for item in comparisons if item.p95_ratio is not None]
    p99_ratios = [item.p99_ratio for item in comparisons if item.p99_ratio is not None]
    return SegmentSummary(
        name=name,
        rows=len(comparisons),
        primary_geomean_ratio=geomean(primary_ratios),
        primary_median_ratio=median(primary_ratios),
        p95_geomean_ratio=geomean(p95_ratios),
        p99_geomean_ratio=geomean(p99_ratios),
    )


def compare_wins(
    old_report: BenchmarkReport,
    new_report: BenchmarkReport,
    focus_client: str,
) -> WinsComparison | None:
    old = wins_for_report(old_report, focus_client)
    new = wins_for_report(new_report, focus_client)
    if old is None or new is None:
        return None
    return WinsComparison(
        old_wins=old.wins,
        new_wins=new.wins,
        comparable_groups=min(old.groups, new.groups),
        old_geomean_to_winner=geomean(old.ratios_to_winner),
        new_geomean_to_winner=geomean(new.ratios_to_winner),
        old_average_rank=mean(old.ranks),
        new_average_rank=mean(new.ranks),
    )


def wins_for_report(report: BenchmarkReport, focus_client: str) -> WinsSnapshot | None:
    if report.suite == "resource-backpressure":
        return None
    grouped: dict[tuple[str, ...], list[BenchmarkRow]] = defaultdict(list)
    for row in report.rows:
        grouped[row.group].append(row)

    wins = 0
    groups = 0
    ratios: list[float] = []
    ranks: list[float] = []
    for rows in grouped.values():
        focus_row = next((row for row in rows if row.client == focus_client), None)
        if focus_row is None:
            continue
        ranked = sorted(rows, key=lambda row: row.primary_value, reverse=True)
        winner = ranked[0]
        groups += 1
        if winner.client == focus_client:
            wins += 1
        ratios.append(safe_ratio(focus_row.primary_value, winner.primary_value))
        ranks.append(float(next(index + 1 for index, row in enumerate(ranked) if row.client == focus_client)))
    return WinsSnapshot(wins=wins, groups=groups, ratios_to_winner=ratios, ranks=ranks)


def error_rows(report: BenchmarkReport) -> list[ErrorRow]:
    rows: list[ErrorRow] = []
    for row in report.rows:
        if row.errors_total == 0 and row.warmup_errors_total == 0:
            continue
        rows.append(
            ErrorRow(
                label=row.label,
                mode=row.mode,
                client=row.client,
                scenario=row.scenario,
                errors_total=row.errors_total,
                warmup_errors_total=row.warmup_errors_total,
                error_rate_percent=row.error_rate_percent,
            ),
        )
    return sorted(rows, key=lambda row: (row.mode, row.client, row.scenario, row.label))


def resource_summary(
    old_rows: Iterable[BenchmarkRow],
    new_rows: Iterable[BenchmarkRow],
) -> ResourceSummary:
    old_list = list(old_rows)
    new_list = list(new_rows)
    return ResourceSummary(
        old_rss_mb_max=max_optional(row.rss_mb for row in old_list),
        new_rss_mb_max=max_optional(row.rss_mb for row in new_list),
        old_threads_max=max_optional_int(row.threads for row in old_list),
        new_threads_max=max_optional_int(row.threads for row in new_list),
        old_fds_max=max_optional_int(row.fds for row in old_list),
        new_fds_max=max_optional_int(row.fds for row in new_list),
        old_errors_total=sum(row.errors_total for row in old_list),
        new_errors_total=sum(row.errors_total for row in new_list),
    )


def safe_ratio(new_value: float, old_value: float) -> float:
    if old_value <= 0:
        return math.inf if new_value > 0 else 1.0
    return new_value / old_value


def optional_ratio(new_value: float | None, old_value: float | None) -> float | None:
    if new_value is None or old_value is None:
        return None
    return safe_ratio(new_value, old_value)


def geomean(values: Iterable[float]) -> float | None:
    present = [value for value in values if value > 0 and math.isfinite(value)]
    if not present:
        return None
    return math.exp(sum(math.log(value) for value in present) / len(present))


def median(values: Iterable[float]) -> float | None:
    present = [value for value in values if math.isfinite(value)]
    if not present:
        return None
    return statistics.median(present)


def mean(values: Iterable[float]) -> float | None:
    present = list(values)
    if not present:
        return None
    return statistics.mean(present)


def max_optional(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def max_optional_int(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None
