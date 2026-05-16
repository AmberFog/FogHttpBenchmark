__all__ = ("ResourceAggregateRow",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceAggregateRow:
    mode: str
    client: str
    scenario: str
    concurrency: int
    request_limit: int
    per_origin_request_limit: int | None
    max_pending_requests: int
    requests: int
    repeats: int
    ok_requests_total: int
    errors_total: int
    warmup_errors_total: int
    error_rate_percent: float
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    duration_s_median: float
    duration_s_cv_percent: float
    rss_mb_max: float | int | None
    threads_max: float | int | None
    fds_max: float | int | None
    peak_active_requests_max: float | int | None
    peak_pending_requests_max: float | int | None
    final_failed_requests_max: int | None
    final_pool_timeouts_max: int | None
    recovery_failures: int
    error_types: dict[str, int]
