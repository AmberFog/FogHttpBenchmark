__all__ = ("aggregate_resource_results",)

from collections.abc import Sequence
from dataclasses import dataclass

from foghttp_benchmark.models import ResourceBackpressureResult
from foghttp_benchmark.resource.reporting.metrics import (
    client_stat_max,
    coefficient_of_variation,
    error_rate,
    median_metric,
    merge_error_types,
    optional_max,
    sum_metric,
)
from foghttp_benchmark.resource.reporting.models import ResourceAggregateRow


@dataclass(frozen=True, slots=True)
class ResourceAggregateKey:
    mode: str
    client: str
    scenario: str
    concurrency: int
    request_limit: int
    per_origin_request_limit: int | None
    max_pending_requests: int
    max_buffered_response_bytes: int | None

    @classmethod
    def from_result(cls, result: ResourceBackpressureResult) -> "ResourceAggregateKey":
        return cls(
            mode=result.mode,
            client=result.client,
            scenario=result.scenario,
            concurrency=result.concurrency,
            request_limit=result.request_limit,
            per_origin_request_limit=result.per_origin_request_limit,
            max_pending_requests=result.max_pending_requests,
            max_buffered_response_bytes=result.max_buffered_response_bytes,
        )

    def sort_key(self) -> tuple[str, str, str, int, int, int, int, int]:
        return (
            self.mode,
            self.client,
            self.scenario,
            self.concurrency,
            self.request_limit,
            -1 if self.per_origin_request_limit is None else self.per_origin_request_limit,
            self.max_pending_requests,
            -1 if self.max_buffered_response_bytes is None else self.max_buffered_response_bytes,
        )


def aggregate_resource_results(results: list[ResourceBackpressureResult]) -> list[ResourceAggregateRow]:
    grouped: dict[ResourceAggregateKey, list[ResourceBackpressureResult]] = {}
    for result in results:
        key = ResourceAggregateKey.from_result(result)
        grouped.setdefault(key, []).append(result)

    return [
        build_aggregate_row(key, items) for key, items in sorted(grouped.items(), key=lambda item: item[0].sort_key())
    ]


def build_aggregate_row(
    key: ResourceAggregateKey,
    results: Sequence[ResourceBackpressureResult],
) -> ResourceAggregateRow:
    requests_total = sum_metric(results, lambda result: result.requests)
    errors_total = sum_metric(results, lambda result: result.errors)
    return ResourceAggregateRow(
        mode=key.mode,
        client=key.client,
        scenario=key.scenario,
        concurrency=key.concurrency,
        request_limit=key.request_limit,
        per_origin_request_limit=key.per_origin_request_limit,
        max_pending_requests=key.max_pending_requests,
        max_buffered_response_bytes=key.max_buffered_response_bytes,
        requests=results[0].requests,
        repeats=len(results),
        ok_requests_total=sum_metric(results, lambda result: result.ok_requests),
        errors_total=errors_total,
        warmup_errors_total=sum_metric(results, lambda result: result.warmup_errors),
        error_rate_percent=error_rate(errors_total, requests_total),
        p50_ms_median=median_metric(results, lambda result: result.p50_ms),
        p95_ms_median=median_metric(results, lambda result: result.p95_ms),
        p99_ms_median=median_metric(results, lambda result: result.p99_ms),
        duration_s_median=median_metric(results, lambda result: result.duration_s),
        duration_s_cv_percent=coefficient_of_variation(
            [result.duration_s for result in results],
        ),
        rss_mb_max=optional_max(result.peak_rss_mb for result in results),
        threads_max=optional_max(result.peak_threads for result in results),
        fds_max=optional_max(result.peak_fds for result in results),
        peak_active_requests_max=optional_max(result.peak_active_requests for result in results),
        peak_pending_requests_max=optional_max(result.peak_pending_requests for result in results),
        peak_buffered_response_bytes_max=optional_max(result.peak_buffered_response_bytes for result in results),
        final_failed_requests_max=client_stat_max(results, "failed_requests"),
        final_pool_timeouts_max=client_stat_max(results, "pool_acquire_timeouts"),
        final_buffered_response_bytes_max=client_stat_max(results, "buffered_response_bytes"),
        final_buffered_response_budget_rejections_max=client_stat_max(
            results,
            "buffered_response_budget_rejections",
        ),
        recovery_failures=sum(1 for result in results if result.recovery_ok is False),
        error_types=merge_error_types(result.error_types for result in results),
    )
