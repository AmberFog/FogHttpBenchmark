__all__ = (
    "aggregate_streaming_results",
    "write_streaming_reports",
)

from collections.abc import Iterable
from dataclasses import asdict
import json
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES, RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import BenchmarkArgs, ClientStatKey
from foghttp_benchmark.provenance import package_sources
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.streaming.models import StreamingAggregateRow, StreamingResult
from foghttp_benchmark.validity.reports import metadata_with_validity


def aggregate_streaming_results(results: list[StreamingResult]) -> list[StreamingAggregateRow]:
    grouped: dict[tuple[str, str, str, str, str, int, int, str, str], list[StreamingResult]] = {}
    for result in results:
        key = (
            result.mode,
            result.client,
            result.case,
            result.read,
            result.consume,
            result.concurrency,
            result.request_limit,
            result.throughput_scope,
            result.timing_scope,
        )
        grouped.setdefault(key, []).append(result)
    return [build_aggregate_row(key, items) for key, items in sorted(grouped.items())]


def build_aggregate_row(
    key: tuple[str, str, str, str, str, int, int, str, str],
    items: list[StreamingResult],
) -> StreamingAggregateRow:
    mode, client, case, read, consume, concurrency, request_limit, throughput_scope, timing_scope = key
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
        warmup_error_types=merge_error_types(item.warmup_error_types for item in items),
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
        bytes_read_total=sum(item.bytes_read_total for item in items),
        chunks_read_total=sum(item.chunks_read_total for item in items),
        verified_eof_bytes_total=sum(item.verified_eof_bytes_total for item in items),
        verified_eof_chunks_total=sum(item.verified_eof_chunks_total for item in items),
        throughput_scope=throughput_scope,
        timing_scope=timing_scope,
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
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": RESPONSE_STREAMING_SUITE,
            "measurement_scope": "shared-client-server-process-v1",
            "streaming_metric_schema_version": 2,
            "bytes_payload_policy": "byte-pattern-0-255-v1",
            "throughput_scopes": sorted({result.throughput_scope for result in results}),
            "timing_scopes": sorted({result.timing_scope for result in results}),
            "args": vars(args),
            "package_versions": package_versions(),
            "package_sources": package_sources(["foghttp"]),
            "skipped": skipped,
        },
        aggregate_rows,
    )
    payload = {
        "metadata": metadata_payload,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    json_path = output_dir / f"{timestamp}.json"
    markdown_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_markdown = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_streaming_markdown_report(timestamp, aggregate, skipped, args, metadata_payload["validity"])
    markdown_path.write_text(markdown)
    latest_markdown.write_text(markdown)


def render_streaming_markdown_report(
    timestamp: str,
    aggregate: list[StreamingAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    validity: object,
) -> str:
    template = report_environment().get_template("streaming_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
        validity=validity,
    )
