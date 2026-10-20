from types import SimpleNamespace

import pytest

from foghttp_benchmark import runner, suite_selection
from foghttp_benchmark.compressed_response import suite as compressed_suite
from foghttp_benchmark.models import AsyncClientSpec
from foghttp_benchmark.one_upstream import runner as one_upstream_runner
from foghttp_benchmark.proxy_connect import runner as proxy_runner
from foghttp_benchmark.resource import runner as resource_runner
from tests.timing.support import TimingHarness


@pytest.fixture
def timing_harness(monkeypatch: pytest.MonkeyPatch) -> TimingHarness:
    harness = TimingHarness()
    clock = SimpleNamespace(perf_counter=harness.perf_counter, process_time=harness.process_time)
    for module in (runner, one_upstream_runner, proxy_runner, resource_runner):
        monkeypatch.setattr(module, "time", clock)
        monkeypatch.setattr(module, "ResourceSampler", harness.sampler)
    monkeypatch.setattr(runner, "gc", SimpleNamespace(collect=harness.collect_garbage))
    monkeypatch.setattr(runner, "run_load_with_progress", harness.request_load)
    monkeypatch.setattr(one_upstream_runner, "run_load_with_progress", harness.one_upstream_load)
    monkeypatch.setattr(proxy_runner, "run_load_with_progress", harness.proxy_load)
    monkeypatch.setattr(resource_runner, "run_case_load_with_progress", harness.request_load)
    monkeypatch.setattr(resource_runner, "TransportStatsSampler", harness.transport_sampler)
    monkeypatch.setattr(resource_runner, "run_recovery_check", harness.recovery)
    monkeypatch.setattr(
        suite_selection,
        "available_clients",
        lambda _clients, _modes: ([AsyncClientSpec("fake", harness.client)], {}),
    )
    monkeypatch.setattr(compressed_suite, "benchmark_server", harness.server)
    monkeypatch.setattr(compressed_suite, "write_reports", harness.write_reports)
    monkeypatch.setattr(compressed_suite, "settle_after_run", harness.settle_after_run)
    return harness
