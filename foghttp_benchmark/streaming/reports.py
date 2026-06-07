__all__ = (
    "aggregate_streaming_results",
    "write_streaming_reports",
)

from collections.abc import Iterable
from dataclasses import asdict
from importlib import import_module
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import sysconfig
import time

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES, RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import BenchmarkArgs, ClientStatKey, JsonObject
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.streaming.models import StreamingAggregateRow, StreamingResult


SITE_PACKAGE_PATH_KEYS = ("purelib", "platlib")


def aggregate_streaming_results(results: list[StreamingResult]) -> list[StreamingAggregateRow]:
    grouped: dict[tuple[str, str, str, str, str, int, int], list[StreamingResult]] = {}
    for result in results:
        key = (
            result.mode,
            result.client,
            result.case,
            result.read,
            result.consume,
            result.concurrency,
            result.request_limit,
        )
        grouped.setdefault(key, []).append(result)
    return [build_aggregate_row(key, items) for key, items in sorted(grouped.items())]


def build_aggregate_row(
    key: tuple[str, str, str, str, str, int, int],
    items: list[StreamingResult],
) -> StreamingAggregateRow:
    mode, client, case, read, consume, concurrency, request_limit = key
    requests_total = sum(item.requests for item in items)
    errors_total = sum(item.errors for item in items)
    return StreamingAggregateRow(
        mode=mode,
        client=client,
        case=case,
        read=read,
        consume=consume,
        concurrency=concurrency,
        request_limit=request_limit,
        requests=items[0].requests,
        repeats=len(items),
        ok_streams_total=sum(item.ok_streams for item in items),
        errors_total=errors_total,
        warmup_errors_total=sum(item.warmup_errors for item in items),
        error_rate_percent=(errors_total / requests_total) * 100 if requests_total else 0.0,
        ok_streams_s_median=statistics.median(item.ok_streams_per_second for item in items),
        streams_s_median=statistics.median(item.streams_per_second for item in items),
        streams_s_cv_percent=coefficient_of_variation([item.streams_per_second for item in items]),
        mb_s_median=statistics.median(item.mb_per_second for item in items),
        lines_s_median=statistics.median(item.lines_per_second for item in items),
        text_chars_read_total=sum(item.text_chars_read_total for item in items),
        lines_read_total=sum(item.lines_read_total for item in items),
        p50_ms_median=statistics.median(item.p50_ms for item in items),
        p95_ms_median=statistics.median(item.p95_ms for item in items),
        p99_ms_median=statistics.median(item.p99_ms for item in items),
        first_chunk_p50_ms_median=optional_median(item.first_chunk_p50_ms for item in items),
        first_chunk_p95_ms_median=optional_median(item.first_chunk_p95_ms for item in items),
        rss_mb_max=max((item.peak_rss_mb or 0.0) for item in items),
        threads_max=max((item.peak_threads or 0) for item in items),
        fds_max=max((item.peak_fds or 0) for item in items),
        final_active_requests_max=client_stat_max(items, "active_requests"),
        final_response_body_closed_max=client_stat_max(items, "response_body_closed"),
        final_response_body_reuse_eligible_max=client_stat_max(items, "response_body_reuse_eligible"),
        final_response_body_aborted_max=client_stat_max(items, "response_body_aborted"),
        final_connections_opened_max=client_stat_max(items, "connections_opened"),
        final_connections_reused_max=client_stat_max(items, "connections_reused"),
        final_connections_closed_max=client_stat_max(items, "connections_closed"),
        final_connections_aborted_max=client_stat_max(items, "connections_aborted"),
        final_idle_connections_max=client_stat_max(items, "idle_connections"),
        error_types=merge_error_types(item.error_types for item in items),
    )


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def optional_median(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return statistics.median(present)


def client_stat_max(items: list[StreamingResult], key: ClientStatKey) -> int | None:
    values = [item.client_stats[key] for item in items if item.client_stats is not None and key in item.client_stats]
    if not values:
        return None
    return max(values)


def merge_error_types(values: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for errors in values:
        for key, count in errors.items():
            merged[key] = merged.get(key, 0) + count
    return merged


def write_streaming_reports(
    results: list[StreamingResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_streaming_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": RESPONSE_STREAMING_SUITE,
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
            ),
            "package_sources": package_sources(["foghttp"]),
            "skipped": skipped,
        },
        "aggregate": [asdict(row) for row in aggregate],
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    markdown_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_markdown = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_streaming_markdown_report(timestamp, aggregate, skipped, args)
    markdown_path.write_text(markdown)
    latest_markdown.write_text(markdown)


def render_streaming_markdown_report(
    timestamp: str,
    aggregate: list[StreamingAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("streaming_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )


def package_sources(names: list[str]) -> dict[str, JsonObject]:
    sources: dict[str, JsonObject] = {}
    for name in names:
        sources[name] = package_source(name)
    return sources


def package_source(name: str) -> JsonObject:
    try:
        module = import_module(name)
    except ImportError:
        return {"status": "not imported"}
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        return {"status": "unknown"}
    module_path = Path(module_file).resolve()
    source: JsonObject = {"module_file": str(module_path)}
    site_package_root = site_package_root_for(module_path)
    if site_package_root is not None:
        source["source_type"] = "installed"
        source["site_packages_root"] = str(site_package_root)
        return source

    git_root = find_git_root(module_path)
    if git_root is None:
        source["source_type"] = "path"
        return source
    source["source_type"] = "local-git"
    source.update(
        {
            "git_root": str(git_root),
            "git_branch": git_output(git_root, "branch", "--show-current"),
            "git_sha": git_output(git_root, "rev-parse", "--short", "HEAD"),
            "git_dirty": bool(git_output(git_root, "status", "--short")),
        },
    )
    return source


def site_package_root_for(path: Path) -> Path | None:
    for root in site_package_roots():
        if path_is_relative_to(path, root):
            return root
    return None


def site_package_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for path_key in SITE_PACKAGE_PATH_KEYS:
        raw_path = sysconfig.get_path(path_key)
        root = Path(raw_path).resolve()
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def find_git_root(path: Path) -> Path | None:
    for parent in [path.parent, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def git_output(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - git args are fixed local benchmark diagnostics.
            ["/usr/bin/git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
