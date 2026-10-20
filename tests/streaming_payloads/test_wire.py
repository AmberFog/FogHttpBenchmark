import asyncio
import hashlib
from itertools import count
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from foghttp_benchmark.streaming import attribution_measure
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from tests.streaming.attribution_support import BODY, AttributionClient, AttributionResponse


CLIENT_PID = 1212
SERVER_PID = 4242


def synthetic_batch(monkeypatch: pytest.MonkeyPatch, *, failed: bool) -> object:
    ticks = count(1_000_000_000, 1_000_000)
    probes: dict[int, int] = {}

    def cpu(pid: int) -> dict[str, object]:
        probes[pid] = probes.get(pid, 0) + 1
        return {
            "pid": pid,
            "probe_started_ns": next(ticks),
            "user_s": probes[pid] / 10 if pid == CLIENT_PID else None,
            "system_s": probes[pid] / 20 if pid == CLIENT_PID else None,
            "reason": None if pid == CLIENT_PID else "SyntheticUnavailable: isolated server counter",
            "probe_finished_ns": next(ticks),
        }

    monkeypatch.setattr(attribution_measure.time, "perf_counter_ns", lambda: next(ticks))
    monkeypatch.setattr(attribution_measure.time, "get_clock_info", lambda _name: SimpleNamespace(resolution=1e-9))
    monkeypatch.setattr(attribution_measure.os, "getpid", lambda: CLIENT_PID)
    monkeypatch.setattr(attribution_measure, "_cpu_snapshot", cpu)
    response = AttributionResponse(
        [BODY[:7]] if failed else [BODY[:7], BODY[7:]],
        error_after_chunks=TimeoutError("read deadline") if failed else None,
    )
    return asyncio.run(
        attribution_measure.measure_async_batch(
            AttributionClient(response),
            "http://example.invalid",
            body_bytes=len(BODY),
            concurrency=1,
            rounds=1,
            config=AttributionConfig(instrumentation="diagnostic"),
            server_pid=SERVER_PID,
            batch=1,
        ),
    )


@pytest.mark.parametrize("failed", [False, True], ids=["complete", "partial-error"])
def test_internal_typing_preserves_the_baseline_json_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failed: bool,
) -> None:
    result = synthetic_batch(monkeypatch, failed=failed)
    fixture = Path(__file__).parent / ("partial-error.json" if failed else "complete.json")

    expected = fixture.read_text().replace(
        "EXPECTED_PAYLOAD_SHA256",
        hashlib.sha256(BODY[:7] if failed else BODY).hexdigest(),
    )
    assert json.dumps(result, indent=2, sort_keys=True) + "\n" == expected
