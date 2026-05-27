__all__ = (
    "ClientCreationAggregateRow",
    "aggregate_creation_results",
    "write_creation_reports",
)

from collections.abc import Iterable
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import TypeVar

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES
from foghttp_benchmark.models import BenchmarkArgs, ClientCreationResult
from foghttp_benchmark.reports import package_versions, report_environment


OptionalMaxValue = TypeVar("OptionalMaxValue", int, float)


@dataclass(frozen=True, slots=True)
class ClientCreationAggregateRow:
    mode: str
    client: str
    scenario: str
    client_count: int
    iterations: int
    repeats: int
    duration_ms_median: float
    ops_s_median: float
    ops_s_cv_percent: float
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    close_p50_ms_median: float | None
    close_p95_ms_median: float | None
    peak_rss_delta_mb_max: float | None
    end_rss_delta_mb_max: float | None
    peak_threads_delta_max: int | None
    end_threads_delta_max: int | None
    peak_fds_delta_max: int | None
    end_fds_delta_max: int | None
    errors_total: int


def aggregate_creation_results(results: list[ClientCreationResult]) -> list[ClientCreationAggregateRow]:
    grouped: dict[tuple[str, str, str, int, int], list[ClientCreationResult]] = {}
    for result in results:
        key = (result.mode, result.client, result.scenario, result.client_count, result.iterations)
        grouped.setdefault(key, []).append(result)

    rows: list[ClientCreationAggregateRow] = []
    for (mode, client, scenario, client_count, iterations), items in sorted(grouped.items()):
        rows.append(
            ClientCreationAggregateRow(
                mode=mode,
                client=client,
                scenario=scenario,
                client_count=client_count,
                iterations=iterations,
                repeats=len(items),
                duration_ms_median=statistics.median(item.duration_s * 1000 for item in items),
                ops_s_median=statistics.median(item.operations_per_second for item in items),
                ops_s_cv_percent=coefficient_of_variation(
                    [item.operations_per_second for item in items],
                ),
                p50_ms_median=statistics.median(item.p50_ms for item in items),
                p95_ms_median=statistics.median(item.p95_ms for item in items),
                p99_ms_median=statistics.median(item.p99_ms for item in items),
                close_p50_ms_median=optional_median([item.close_p50_ms for item in items]),
                close_p95_ms_median=optional_median([item.close_p95_ms for item in items]),
                peak_rss_delta_mb_max=optional_max([item.peak_rss_delta_mb for item in items]),
                end_rss_delta_mb_max=optional_max([item.end_rss_delta_mb for item in items]),
                peak_threads_delta_max=optional_max([item.peak_threads_delta for item in items]),
                end_threads_delta_max=optional_max([item.end_threads_delta for item in items]),
                peak_fds_delta_max=optional_max([item.peak_fds_delta for item in items]),
                end_fds_delta_max=optional_max([item.end_fds_delta for item in items]),
                errors_total=sum(item.errors for item in items),
            ),
        )
    return rows


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def optional_median(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.median(present) if present else None


def optional_max(values: Iterable[OptionalMaxValue | None]) -> OptionalMaxValue | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def write_creation_reports(
    results: list[ClientCreationResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_creation_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": args.suite,
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
            ),
            "skipped": skipped,
        },
        "aggregate": [asdict(row) for row in aggregate],
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_creation_markdown_report(timestamp, aggregate, skipped, args)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_creation_markdown_report(
    timestamp: str,
    aggregate: list[ClientCreationAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("creation_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )
