import asyncio
from pathlib import Path

import pytest

from foghttp_benchmark.streaming.lifecycle_controls import UnsettledWorkers
from foghttp_benchmark.streaming.lifecycle_worker import _run_async
from tests.streaming.lifecycle_support import (
    closed_observation_case,
    metadata_worker_case,
    stubborn_cancellation_probe,
    unsettled_worker_case,
)


def test_unsettled_cancellation_is_bounded_and_preserves_ownership() -> None:
    error, task_still_running = stubborn_cancellation_probe()
    assert isinstance(error, UnsettledWorkers)
    assert "did not settle" in str(error)
    assert task_still_running


def test_worker_rechecks_provenance_after_owned_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = metadata_worker_case(tmp_path, monkeypatch, "foghttp", changed_provenance=True)

    assert report["status"] == "failed"
    assert report["errors"][0]["type"] == "ValueError"
    assert "provenance changed" in report["errors"][0]["message"]


def test_worker_does_not_close_client_before_unsettled_workers_are_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, adapter = unsettled_worker_case(tmp_path, monkeypatch)
    with pytest.raises(UnsettledWorkers):
        asyncio.run(_run_async(worker))
    assert not adapter.closed
    assert worker.report["force_reap_reason"] == "Owned worker deliberately did not settle"
    assert worker.errors[0]["stage"] == "cancellation-settlement"
    assert (tmp_path / "client.json").exists()


def test_post_close_phase_does_not_query_closed_client_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, phases = closed_observation_case(tmp_path, monkeypatch)
    worker.observe_closed()
    assert worker.stats["after_client_close"] is None
    assert "unavailable" in worker.report["after_close_stats_unavailable_reason"]
    assert phases == ["after_client_close"]


@pytest.mark.parametrize("client", ["foghttp", "httpx"])
def test_worker_records_actual_gc_and_client_timeout_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
) -> None:
    report = metadata_worker_case(tmp_path, monkeypatch, client)
    assert report["status"] == "ok"
    configuration = report["client_configuration"]
    assert configuration["total_timeout_s"] == (10.0 if client == "foghttp" else None)
    assert configuration["read_timeout_s"] == configuration["pool_timeout_s"] == report["config"]["settle_timeout_s"]
    assert configuration["trust_env"] is False
    if client == "httpx":
        assert "per-operation" in configuration["total_timeout_unavailable_reason"]
    assert report["gc_configuration"]["enabled"] is False
    assert report["gc_configuration"]["threshold"] == [123, 45, 6]
    assert report["proxy_environment_presence"]["HTTP_PROXY"] is True
    assert "private-credentials" not in str(report)
