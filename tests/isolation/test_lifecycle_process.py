import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from unittest.mock import Mock, call

import pytest

from foghttp_benchmark.isolation import lifecycle
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from tests.isolation.lifecycle_process_support import (
    DESCENDANT_CODE,
    FORCE_REAP_CODE,
    HANG_CODE,
    SERVER_CODE,
    completed_process_pair,
    configure_dead_group_permission_error,
    configure_exit_race,
    configure_fixtures,
    configure_live_group_permission_error,
    process_alive,
    process_executing,
)


CASE = LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1)
CONFIG = LifecycleConfig(case_timeout_s=3, settle_timeout_s=0.1, sample_interval_s=0.01)
DISTINCT_PID_COUNT = 3
TEST_TIMEOUT_S = 3
SERVER_FAILURE_CODE = 23


def test_parent_samples_distinct_processes_and_retains_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_fixtures(monkeypatch)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "ok", receipt["failures"]
    assert len({receipt["parent_pid"], receipt["client_pid"], receipt["server_pid"]}) == DISTINCT_PID_COUNT
    assert receipt["client_report"]["pid"] == receipt["client_pid"]
    assert receipt["report_path"] == str(tmp_path / "case" / "client.json")
    phases = receipt["resources"]["phases"]
    assert phases[0]["phase"] == "before-load"
    assert phases[0]["client"]["pid"] == receipt["client_pid"]
    assert phases[0]["server"]["pid"] == receipt["server_pid"]
    assert "fixture client done" in receipt["client_stdout_tail"]
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])
    assert (tmp_path / "case" / "receipt.json").is_file()


def test_hard_timeout_kills_term_ignoring_child_and_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_fixtures(monkeypatch, HANG_CODE)
    config = replace(CONFIG, case_timeout_s=0.4)
    started = time.monotonic()

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, config, tmp_path / "case"))

    assert time.monotonic() - started < TEST_TIMEOUT_S
    assert receipt["status"] == "failed"
    assert "deadline" in receipt["failure"]
    assert "fixture client waits" in receipt["client_stdout_tail"]
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_parent_cancellation_reaps_both_and_persists_partial_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch, HANG_CODE)

    async def cancel() -> None:
        output = tmp_path / "case"
        task = asyncio.create_task(lifecycle.run_lifecycle_case(CASE, CONFIG, output))
        async with asyncio.timeout(3):
            while True:
                if (output / "client-pid").exists():
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(cancel())
    receipt = json.loads((tmp_path / "case" / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert "cancelled" in receipt["failure"]
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_partial_startup_failure_reaps_server_and_preserves_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch)
    monkeypatch.setattr(lifecycle, "client_command", lambda *_args: [str(tmp_path / "missing-executable")])

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "failed"
    assert "FileNotFoundError" in receipt["failure"]
    assert receipt["client_pid"] is None
    assert not process_alive(receipt["server_pid"])
    assert "fixture server ready" in receipt["server_stdout_tail"]


def test_server_exit_invalidates_case_and_reaps_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_fixtures(monkeypatch, HANG_CODE)
    code = SERVER_CODE.replace("time.sleep(100)", "time.sleep(0.2); sys.exit(23)")
    monkeypatch.setattr(lifecycle, "server_command", lambda _config, ready: [sys.executable, "-c", code, str(ready)])

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "failed"
    assert "Server exited" in receipt["failure"]
    assert receipt["server_returncode"] == SERVER_FAILURE_CODE
    assert not process_alive(receipt["client_pid"])


def test_out_of_order_marker_never_acks_or_hides_control_failure(tmp_path: Path) -> None:
    control = tmp_path / "control"
    control.mkdir()
    lifecycle.write_object(control / "marker.json", {"sequence": 2, "phase": "before-load"})
    sampler = lifecycle.LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)

    with pytest.raises(ValueError, match="Out-of-order"):
        lifecycle.check_marker(control, sampler, 0)

    assert not (control / "ack.json").exists()


def test_cleanup_kills_descendant_after_its_group_leader_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_fixtures(monkeypatch, DESCENDANT_CODE)
    config = replace(CONFIG, case_timeout_s=0.4)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, config, tmp_path / "case"))

    descendant_pid = int((tmp_path / "case" / "client-pid").read_text())
    assert "deadline" in receipt["failure"]
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])
    assert not process_executing(descendant_pid)


def test_unsettled_worker_requests_immediate_parent_reap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_fixtures(monkeypatch, FORCE_REAP_CODE)
    started = time.monotonic()

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert time.monotonic() - started < CONFIG.case_timeout_s
    assert "requested forced process cleanup" in receipt["failure"]
    assert receipt["client_report"]["force_reap_reason"] == "owned worker refused cancellation"
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


@pytest.mark.parametrize("completion_lag", [False, True])
def test_client_exit_between_poll_and_probe_preserves_null_and_reaps_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    completion_lag: bool,
) -> None:
    configure_fixtures(monkeypatch)
    configure_exit_race(monkeypatch, completion_lag=completion_lag)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "ok", receipt["failures"]
    assert receipt["returncode"] == 0
    terminated = [sample for sample in receipt["resources"]["samples"] if sample["process_terminated"]]
    assert terminated
    for sample in terminated:
        assert sample["rss_bytes"] is None
        assert sample["termination_reason"]
        assert sample["role"] == "client"
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_access_denied_rss_remains_failure_after_confirmed_child_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch)
    configure_exit_race(monkeypatch, deny_rss=True)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "failed"
    assert "Cannot enforce RSS ceiling" in receipt["failure"]
    denied = [sample for sample in receipt["resources"]["samples"] if sample["rss_bytes"] is None]
    assert denied
    assert all(not sample["process_terminated"] for sample in denied)
    assert receipt["returncode"] == 0
    assert not process_alive(receipt["server_pid"])


def test_dead_group_permission_error_requires_confirmed_exit_and_empty_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch)
    configure_exit_race(monkeypatch)
    verified = configure_dead_group_permission_error(monkeypatch, tmp_path / "case" / "client.json")

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "ok", receipt["failures"]
    assert verified == [receipt["client_pid"], receipt["client_pid"]]
    assert receipt["returncode"] == 0
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_live_group_permission_error_remains_failure_and_other_child_is_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch, HANG_CODE)
    configure_live_group_permission_error(monkeypatch, tmp_path / "case" / "client-pid")

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, replace(CONFIG, case_timeout_s=0.4), tmp_path / "case"))

    assert receipt["status"] == "failed"
    assert any("Cannot signal owned client group" in failure for failure in receipt["failures"])
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_completed_group_can_quiesce_within_declared_confirmation_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch)
    configure_exit_race(monkeypatch)
    configure_dead_group_permission_error(monkeypatch, tmp_path / "case" / "client.json")
    group_members = Mock(side_effect=(True, False, False))
    monkeypatch.setattr(lifecycle, "group_has_live_members", group_members)

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert receipt["status"] == "ok", receipt["failures"]
    assert group_members.call_args_list == [call(receipt["client_pid"])] * 3
    assert receipt["returncode"] == 0
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


def test_group_still_live_after_confirmation_window_remains_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fixtures(monkeypatch)
    configure_exit_race(monkeypatch)
    configure_dead_group_permission_error(monkeypatch, tmp_path / "case" / "client.json")
    monkeypatch.setattr(lifecycle, "group_has_live_members", Mock(return_value=True))
    started = time.monotonic()

    receipt = asyncio.run(lifecycle.run_lifecycle_case(CASE, CONFIG, tmp_path / "case"))

    assert time.monotonic() - started < TEST_TIMEOUT_S
    assert receipt["status"] == "failed"
    assert "Cannot signal owned client group" in receipt["failure"]
    assert receipt["returncode"] == 0
    assert not process_alive(receipt["client_pid"])
    assert not process_alive(receipt["server_pid"])


@pytest.mark.parametrize("server_code", [0, SERVER_FAILURE_CODE])
def test_server_exit_is_invalid_when_both_processes_finish_between_polls(tmp_path: Path, server_code: int) -> None:
    client, server = completed_process_pair(tmp_path, server_code)
    sampler = lifecycle.LifecycleResourceSampler(interval_s=0.05, max_samples=10, rss_ceiling_bytes=100)

    failures = asyncio.run(lifecycle.monitor_client(client, server, tmp_path, sampler, deadline=time.monotonic() + 1))

    assert failures == [f"Server exited before owned shutdown with code {server_code}"]
    assert not process_alive(client.process.pid)
    assert not process_alive(server.process.pid)
