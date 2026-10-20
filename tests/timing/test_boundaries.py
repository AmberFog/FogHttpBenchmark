import asyncio

import pytest

from foghttp_benchmark.compressed_response.scenarios import compressed_response_scenarios
from foghttp_benchmark.models import RunResult
from tests.timing.cases import REQUESTS, SUITES, Suite, run_case
from tests.timing.support import PEAK_FDS, PEAK_RSS_MB, PEAK_THREADS, WORKLOAD_CPU_S, WORKLOAD_DURATION_S, TimingHarness


@pytest.mark.parametrize("suite", SUITES)
def test_measured_duration_excludes_sampler_and_lifecycle_overhead(suite: Suite, timing_harness: TimingHarness) -> None:
    result = asyncio.run(run_case(suite, timing_harness))

    assert result.duration_s == WORKLOAD_DURATION_S
    assert timing_harness.wall_s > WORKLOAD_DURATION_S
    assert result.ok_requests == REQUESTS - 1
    assert result.errors == 1
    assert result.warmup_errors == 1
    assert result.error_types == {"measured_failure": 1}
    assert result.warmup_error_types == {"warmup_failure": 1}
    assert result.peak_rss_mb == PEAK_RSS_MB
    assert result.peak_threads == PEAK_THREADS
    assert result.peak_fds == PEAK_FDS
    if isinstance(result, RunResult):
        assert result.process_cpu_s == WORKLOAD_CPU_S
    assert timing_harness.events[0] == "create"
    assert timing_harness.events.index("stats") < timing_harness.events.index("close")
    assert timing_harness.events[-1] == ("settle" if suite == "compressed-response" else "close")
    assert timing_harness.events.index("warmup") < timing_harness.events.index("resources-enter")
    assert timing_harness.events.index("resources-exit") < timing_harness.events.index("stats")
    if suite == "resource":
        assert timing_harness.events.index("resources-enter") < timing_harness.events.index("transport-enter")
        assert timing_harness.events.index("transport-enter") < timing_harness.events.index("measured")
        assert timing_harness.events.index("measured") < timing_harness.events.index("transport-exit")
        assert timing_harness.events.index("transport-exit") < timing_harness.events.index("resources-exit")
        assert timing_harness.events.index("resources-exit") < timing_harness.events.index("recovery")
    else:
        assert result.requests_per_second == REQUESTS / WORKLOAD_DURATION_S
        assert result.ok_requests_per_second == (REQUESTS - 1) / WORKLOAD_DURATION_S
    if suite == "compressed-response":
        assert timing_harness.scenarios == [compressed_response_scenarios()["gzip-64k"]] * 2


@pytest.mark.parametrize("suite", SUITES)
@pytest.mark.parametrize("phase", ["warmup", "measured"])
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
def test_failure_propagates_after_sampler_and_client_cleanup(
    suite: Suite,
    phase: str,
    failure_type: type[BaseException],
    timing_harness: TimingHarness,
) -> None:
    failure = failure_type("injected workload failure")
    timing_harness.failure = failure
    timing_harness.failure_phase = phase

    with pytest.raises(failure_type) as raised:
        asyncio.run(run_case(suite, timing_harness))

    assert raised.value is failure
    assert timing_harness.events[-1] == "close"
    assert timing_harness.events.count("close") == 1
    assert "stats" not in timing_harness.events
    assert "recovery" not in timing_harness.events
    if phase == "warmup":
        assert "resources-enter" not in timing_harness.events
    else:
        assert timing_harness.events.index("measured") < timing_harness.events.index("resources-exit")
        assert timing_harness.events.index("resources-exit") < timing_harness.events.index("close")
        if suite == "resource":
            assert timing_harness.events.index("measured") < timing_harness.events.index("transport-exit")
            assert timing_harness.events.index("transport-exit") < timing_harness.events.index("resources-exit")
