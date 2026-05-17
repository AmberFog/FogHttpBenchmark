from dataclasses import dataclass

from foghttp_benchmark.clients.utils import client_stats_from_raw


@dataclass(frozen=True, slots=True)
class RawTransportStats:
    active_requests: int
    pending_requests: int
    total_requests: int
    failed_requests: int
    pool_acquire_timeouts: int


def test_client_stats_from_dataclass_keeps_known_transport_fields() -> None:
    stats = client_stats_from_raw(
        RawTransportStats(
            active_requests=3,
            pending_requests=5,
            total_requests=13,
            failed_requests=2,
            pool_acquire_timeouts=1,
        ),
    )

    assert stats == {
        "active_requests": 3,
        "pending_requests": 5,
        "total_requests": 13,
        "failed_requests": 2,
        "pool_acquire_timeouts": 1,
    }


def test_client_stats_from_mapping_ignores_unknown_and_non_integer_values() -> None:
    stats = client_stats_from_raw(
        {
            "active_requests": 3,
            "pending_requests": True,
            "total_requests": "13",
            "failed_requests": 2,
            "pool_acquire_timeouts": 1,
            "future_metric": 99,
        },
    )

    assert stats == {
        "active_requests": 3,
        "failed_requests": 2,
        "pool_acquire_timeouts": 1,
    }
