from dataclasses import dataclass

from foghttp_benchmark.clients.utils import client_stats_from_raw


@dataclass(frozen=True, slots=True)
class RawTransportStats:
    active_requests: int
    pending_requests: int
    peak_pending_requests: int
    total_requests: int
    failed_requests: int
    pool_acquire_attempts: int
    pool_acquire_immediate: int
    pool_acquire_waited: int
    pool_acquire_timeouts: int
    pool_acquire_wait_time_total_ns: int
    pool_acquire_wait_time_max_ns: int
    pool_acquire_wait_time_last_ns: int
    buffered_response_bytes: int
    buffered_response_budget_rejections: int


def test_client_stats_from_dataclass_keeps_known_transport_fields() -> None:
    stats = client_stats_from_raw(
        RawTransportStats(
            active_requests=3,
            pending_requests=5,
            peak_pending_requests=8,
            total_requests=13,
            failed_requests=2,
            pool_acquire_attempts=21,
            pool_acquire_immediate=17,
            pool_acquire_waited=4,
            pool_acquire_timeouts=1,
            pool_acquire_wait_time_total_ns=900,
            pool_acquire_wait_time_max_ns=500,
            pool_acquire_wait_time_last_ns=100,
            buffered_response_bytes=2048,
            buffered_response_budget_rejections=6,
        ),
    )

    assert stats == {
        "active_requests": 3,
        "pending_requests": 5,
        "peak_pending_requests": 8,
        "total_requests": 13,
        "failed_requests": 2,
        "pool_acquire_attempts": 21,
        "pool_acquire_immediate": 17,
        "pool_acquire_waited": 4,
        "pool_acquire_timeouts": 1,
        "pool_acquire_wait_time_total_ns": 900,
        "pool_acquire_wait_time_max_ns": 500,
        "pool_acquire_wait_time_last_ns": 100,
        "buffered_response_bytes": 2048,
        "buffered_response_budget_rejections": 6,
    }


def test_client_stats_from_mapping_ignores_unknown_and_non_integer_values() -> None:
    stats = client_stats_from_raw(
        {
            "active_requests": 3,
            "pending_requests": True,
            "peak_pending_requests": 8,
            "total_requests": "13",
            "failed_requests": 2,
            "pool_acquire_timeouts": 1,
            "buffered_response_budget_rejections": 6,
            "future_metric": 99,
        },
    )

    assert stats == {
        "active_requests": 3,
        "peak_pending_requests": 8,
        "failed_requests": 2,
        "pool_acquire_timeouts": 1,
        "buffered_response_budget_rejections": 6,
    }
