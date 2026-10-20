__all__ = (
    "aggregate_streaming_results",
    "write_streaming_reports",
)

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
import platform
import statistics
import sys
import time

from foghttp_benchmark.constants import RESPONSE_STREAMING_SUITE
from foghttp_benchmark.measurement_timing import current_timing_scope, report_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, ClientStatKey
from foghttp_benchmark.provenance import package_sources
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.resource_metrics import (
    RESOURCE_METRIC_SCHEMA_VERSION,
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types
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
    stat_keys: tuple[ClientStatKey, ...] = (
        "active_requests",
        "response_body_closed",
        "response_body_reuse_eligible",
        "response_body_aborted",
        "connections_opened",
        "connections_reused",
        "connections_closed",
        "connections_aborted",
        "idle_connections",
    )
    stats = {key: client_stat_values(items, key) for key in stat_keys}
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
        rss_mb_max=optional_resource_max(item.peak_rss_mb for item in items),
        threads_max=optional_resource_max(item.peak_threads for item in items),
        fds_max=optional_resource_max(item.peak_fds for item in items),
        final_active_requests_max=optional_resource_max(stats["active_requests"]),
        final_response_body_closed_max=optional_resource_max(stats["response_body_closed"]),
        final_response_body_reuse_eligible_max=optional_resource_max(stats["response_body_reuse_eligible"]),
        final_response_body_aborted_max=optional_resource_max(stats["response_body_aborted"]),
        final_connections_opened_max=optional_resource_max(stats["connections_opened"]),
        final_connections_reused_max=optional_resource_max(stats["connections_reused"]),
        final_connections_closed_max=optional_resource_max(stats["connections_closed"]),
        final_connections_aborted_max=optional_resource_max(stats["connections_aborted"]),
        final_idle_connections_max=optional_resource_max(stats["idle_connections"]),
        error_types=merge_error_types(item.error_types for item in items),
        resource_coverage=resource_coverage(
            {
                "rss_mb_max": [item.peak_rss_mb for item in items],
                "threads_max": [item.peak_threads for item in items],
                "fds_max": [item.peak_fds for item in items],
                **{f"final_{key}_max": values for key, values in stats.items()},
            },
        ),
        bytes_read_total=sum(item.bytes_read_total for item in items),
        chunks_read_total=sum(item.chunks_read_total for item in items),
        verified_eof_bytes_total=sum(item.verified_eof_bytes_total for item in items),
        verified_eof_chunks_total=sum(item.verified_eof_chunks_total for item in items),
        throughput_scope=throughput_scope,
        timing_scope=timing_scope,
    )


def optional_median(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return statistics.median(present)


def client_stat_values(items: list[StreamingResult], key: ClientStatKey) -> list[int | None]:
    return [item.client_stats.get(key) if item.client_stats is not None else None for item in items]


def write_streaming_reports(
    results: list[StreamingResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_streaming_results(results)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    timing_scopes = sorted({result.timing_scope for result in results})
    timing_scope = (
        report_timing_scope(RESPONSE_STREAMING_SUITE, {"timing_scopes": timing_scopes}, aggregate_rows)
        if results
        else current_timing_scope(RESPONSE_STREAMING_SUITE)
    )
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": RESPONSE_STREAMING_SUITE,
            "measurement_scope": "shared-client-server-process-v1",
            "streaming_metric_schema_version": 2,
            "timing_scope": timing_scope,
            "resource_metric_schema_version": RESOURCE_METRIC_SCHEMA_VERSION,
            "bytes_payload_policy": "byte-pattern-0-255-v1",
            "throughput_scopes": sorted({result.throughput_scope for result in results}),
            "timing_scopes": timing_scopes,
            "args": vars(args),
            "package_versions": package_versions(),
            "package_sources": package_sources(["foghttp"]),
            "skipped": skipped,
        },
        aggregate_rows,
    )
    payload: dict[str, object] = {
        "metadata": metadata_payload,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    markdown = render_suite_markdown(
        load_report_template("streaming_report.md.j2"),
        SuiteRenderContext(
            timestamp=timestamp,
            args=args,
            aggregate=aggregate,
            skipped=skipped,
            validity=metadata_payload["validity"],
            environment=RenderEnvironment(
                python_version=platform.python_version(),
                platform_name=platform.platform(),
            ),
        ),
    )
    publish_report(output_dir, timestamp, payload, markdown)
