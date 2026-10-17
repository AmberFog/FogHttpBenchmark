import importlib
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from foghttp_benchmark.isolation import lifecycle_resources
from foghttp_benchmark.isolation.lifecycle_resources import (
    EXIT_CONFIRMATION_TIMEOUT_S,
    LifecycleResourceSampler,
    ProcessResourceProbe,
    ResourceSample,
    cpu_delta,
)


FAKE_PID = 123456789
EXPECTED_RSS = 1234
EXPECTED_THREADS = 3
EXPECTED_CPU_USER = 1.25
EXPECTED_CPU_SYSTEM = 0.5
EXPECTED_CPU_DELTA = 0.25
CLIENT_RSS = 90
SERVER_RSS = 110
PHASE_RSS = 80
LIFETIME_RSS = 500


def test_current_rss_is_bytes_and_optional_metrics_keep_reasons() -> None:
    probe = ProcessResourceProbe("client", FAKE_PID)
    probe.process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=EXPECTED_RSS),
        num_threads=lambda: EXPECTED_THREADS,
        cpu_times=lambda: SimpleNamespace(user=EXPECTED_CPU_USER, system=EXPECTED_CPU_SYSTEM),
    )
    sample = probe.sample("before-load")

    assert sample.rss_bytes == EXPECTED_RSS
    assert sample.threads == EXPECTED_THREADS
    assert sample.fds is None
    assert "AttributeError" in sample.unavailable["fds"]
    assert sample.cpu_user_s == EXPECTED_CPU_USER
    assert sample.cpu_system_s == EXPECTED_CPU_SYSTEM
    assert sample.pid == FAKE_PID
    assert sample.role == "client"


def test_missing_process_does_not_substitute_lifetime_peak_or_zero() -> None:
    probe = ProcessResourceProbe("server", 123456789)
    probe.process = None
    probe.reason = "Process already exited"

    payload = probe.sample("closed").payload()

    for metric in ("rss_bytes", "threads", "fds", "cpu_user_s", "cpu_system_s"):
        assert payload[metric] is None
        assert payload["unavailable"][metric] == "Process already exited"


def test_cpu_deltas_preserve_phase_and_missing_counter() -> None:
    before = ResourceSample("client", 101, 1000, "before", cpu_user_s=0.5, cpu_system_s=0.2)
    after = ResourceSample("client", 101, 2000, "after", cpu_user_s=0.75)
    after.unavailable["cpu_system_s"] = "Access denied"

    delta = cpu_delta(before, after)

    assert delta["user_s"] == EXPECTED_CPU_DELTA
    assert delta["system_s"] is None
    assert delta["from_phase"] == "before"
    assert delta["to_phase"] == "after"
    assert delta["unavailable"] == {"system_s": "Access denied"}


def test_sampler_bounds_series_and_applies_ceiling_to_each_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=1, rss_ceiling_bytes=100)
    sampler.attach("client", 101)
    sampler.attach("server", 102)
    monkeypatch.setattr(
        sampler.probes["client"],
        "sample",
        lambda phase: ResourceSample("client", 101, 1, phase, CLIENT_RSS),
    )
    monkeypatch.setattr(
        sampler.probes["server"],
        "sample",
        lambda phase: ResourceSample("server", 102, 2, phase, SERVER_RSS),
    )

    _, failures = sampler.sample("load")

    assert len(sampler.samples) == 1
    assert sampler.truncated
    assert failures == [
        "Resource sample cap reached; incomplete series",
        "server PID 102 exceeded RSS ceiling 100 bytes",
    ]
    assert sampler.peaks["client"]["rss_bytes"] == CLIENT_RSS
    assert sampler.peaks["server"]["rss_bytes"] == SERVER_RSS


def test_phase_barrier_samples_both_processes_and_keeps_lifetime_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    for role, pid in (("client", 101), ("server", 102)):
        sampler.attach(role, pid)
        monkeypatch.setattr(
            sampler.probes[role],
            "sample",
            lambda phase, role=role, pid=pid: ResourceSample(role, pid, 1, phase, rss_bytes=PHASE_RSS),
        )

    sampler.mark({"sequence": 1, "phase": "before-load", "lifetime_high_water_rss_bytes": LIFETIME_RSS})

    phase = sampler.payload()["phases"][0]
    assert phase["client"]["rss_bytes"] == PHASE_RSS
    assert phase["server"]["rss_bytes"] == PHASE_RSS
    assert phase["worker"]["lifetime_high_water_rss_bytes"] == LIFETIME_RSS
    assert sampler.peaks["client"]["rss_bytes"] != LIFETIME_RSS


def test_missing_current_rss_explicitly_fails_ceiling_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    sampler.attach("client", 101)
    sample = ResourceSample("client", 101, 1, "before-load")
    sample.unavailable["rss_bytes"] = "Access denied"
    monkeypatch.setattr(sampler.probes["client"], "sample", lambda _phase: sample)

    _, failures = sampler.sample("before-load")

    assert failures == ["Cannot enforce RSS ceiling for client PID 101: Access denied"]
    assert sampler.peaks["client"]["rss_bytes"] is None


def test_observed_intervals_come_from_each_role_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    sampler.attach("client", 101)
    samples = iter(
        (
            ResourceSample("client", 101, 1_000_000_000, "before", rss_bytes=PHASE_RSS),
            ResourceSample("client", 101, 1_080_000_000, "after", rss_bytes=PHASE_RSS),
        ),
    )
    monkeypatch.setattr(sampler.probes["client"], "sample", lambda _phase: next(samples))
    sampler.sample("before")
    sampler.sample("after")

    assert sampler.payload()["observed_intervals_s"] == {
        "client": {"count": 1, "min": 0.08, "max": 0.08, "median": 0.08, "includes_phase_barrier_samples": True},
    }


def test_no_such_process_waits_boundedly_for_waitpid_and_counts_probe_overhead(monkeypatch: pytest.MonkeyPatch) -> None:
    wait = Mock(return_value=0)
    probe = ProcessResourceProbe("client", FAKE_PID, completion=lambda: None, wait_for_exit=wait)
    ticks = iter((1_000_000_000, 1_020_000_000))
    monkeypatch.setattr(lifecycle_resources.time, "monotonic_ns", lambda: next(ticks))

    sample = probe.sample("post_gc")

    wait.assert_called_once_with(EXIT_CONFIRMATION_TIMEOUT_S)
    assert sample.process_terminated
    assert sample.rss_bytes is None
    assert sample.termination_reason
    assert sample.probe_duration_ns == 1_020_000_000 - 1_000_000_000


def test_no_such_process_unconfirmed_after_bounded_wait_retains_rss_failure() -> None:
    wait = Mock(side_effect=subprocess.TimeoutExpired("fixture owned process", EXIT_CONFIRMATION_TIMEOUT_S))
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    sampler.attach("client", FAKE_PID, completion=lambda: None, wait_for_exit=wait)

    observations, failures = sampler.sample("post_gc")

    wait.assert_called_once_with(EXIT_CONFIRMATION_TIMEOUT_S)
    assert not observations["client"].process_terminated
    assert observations["client"].rss_bytes is None
    assert len(failures) == 1
    assert "Cannot enforce RSS ceiling" in failures[0]


@pytest.mark.parametrize("completion_lag", [False, True])
def test_zero_rss_needs_owned_exit_confirmation_and_is_never_a_live_sample(*, completion_lag: bool) -> None:
    wait = Mock(return_value=0)
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    sampler.attach("client", FAKE_PID, completion=lambda: None if completion_lag else 0, wait_for_exit=wait)
    sampler.probes["client"].process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=0),
        num_threads=lambda: 1,
        num_fds=lambda: 0,
        cpu_times=lambda: SimpleNamespace(user=0.25, system=0.1),
    )

    observations, failures = sampler.sample("post_gc")

    sample = observations["client"]
    assert failures == []
    assert sample.rss_bytes is None
    assert sample.process_terminated
    assert "confirmed return code 0" in sample.termination_reason
    assert "returned zero" in sample.unavailable["rss_bytes"]
    assert sampler.samples[0]["rss_bytes"] is None
    assert sampler.peaks["client"]["rss_bytes"] is None
    if completion_lag:
        wait.assert_called_once_with(EXIT_CONFIRMATION_TIMEOUT_S)
    else:
        wait.assert_not_called()


@pytest.mark.parametrize("has_completion", [False, True])
def test_zero_rss_without_exit_proof_retains_the_ceiling_failure(*, has_completion: bool) -> None:
    wait = Mock(side_effect=subprocess.TimeoutExpired("fixture owned process", EXIT_CONFIRMATION_TIMEOUT_S))
    sampler = LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)
    sampler.attach("client", FAKE_PID, completion=(lambda: None) if has_completion else None, wait_for_exit=wait)
    sampler.probes["client"].process = SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=0))

    observations, failures = sampler.sample("post_gc")

    sample = observations["client"]
    assert sample.rss_bytes is None
    assert not sample.process_terminated
    assert sample.termination_reason is None
    assert len(failures) == 1
    assert "Cannot enforce RSS ceiling" in failures[0]
    assert "returned zero" in failures[0]
    assert sampler.peaks["client"]["rss_bytes"] is None
    if has_completion:
        wait.assert_called_once_with(EXIT_CONFIRMATION_TIMEOUT_S)
    else:
        wait.assert_not_called()


def test_access_denied_never_uses_exit_confirmation_wait() -> None:
    psutil = importlib.import_module("psutil")
    wait = Mock(return_value=0)
    probe = ProcessResourceProbe("client", FAKE_PID, completion=lambda: None, wait_for_exit=wait)
    probe.process = SimpleNamespace(memory_info=Mock(side_effect=psutil.AccessDenied(FAKE_PID)))

    sample = probe.sample("post_gc")

    wait.assert_not_called()
    assert not sample.process_terminated
    assert sample.rss_bytes is None
    assert "AccessDenied" in sample.unavailable["rss_bytes"]
