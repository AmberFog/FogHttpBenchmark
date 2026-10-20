from foghttp_benchmark.streaming.attribution_measure import _cpu_delta
from foghttp_benchmark.streaming.attribution_payloads import CpuSnapshot


def snapshot(user: float, system: float, *, started: int) -> CpuSnapshot:
    return {
        "pid": 1,
        "probe_started_ns": started,
        "probe_finished_ns": started + 10,
        "user_s": user,
        "system_s": system,
        "reason": None,
    }


def test_cpu_delta_keeps_available_cpu_but_not_byte_normalization_after_failed_streams() -> None:
    user, system = 0.5, 0.25
    before = snapshot(0.0, 0.0, started=0)
    after = snapshot(user, system, started=1_000_000_010)

    delta = _cpu_delta(before, after, started_ns=10, finished_ns=1_000_000_010, verified_bytes=0)

    assert delta["user_s"] == user
    assert delta["system_s"] == system
    assert delta["total_s"] == user + system
    assert delta["cpu_seconds_per_wall_second"] == user + system
    assert delta["cpu_seconds_per_verified_byte"] is None
    assert delta["normalization_unavailable_reason"] == "No verified-success bytes"
    assert delta["unavailable_reason"] is None
    assert delta["before"] is before
    assert delta["after"] is after


def test_decreased_cpu_counter_is_unavailable_instead_of_a_negative_cost() -> None:
    before = snapshot(0.5, 0.25, started=0)
    after = snapshot(0.25, 0.5, started=1_000_000_010)

    delta = _cpu_delta(before, after, started_ns=10, finished_ns=1_000_000_010, verified_bytes=32)

    for field in ("user_s", "system_s", "total_s", "cpu_seconds_per_verified_byte", "cpu_seconds_per_wall_second"):
        assert delta[field] is None
    assert delta["unavailable_reason"] == "Process CPU counter decreased"
    assert delta["normalization_unavailable_reason"] is None
