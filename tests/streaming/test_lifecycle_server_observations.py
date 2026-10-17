import asyncio

import pytest

from tests.streaming.server_observation_support import (
    BODY_BYTES,
    WRITE_BYTES,
    cancelled_exchange,
    completed_exchange,
    gated_exchange,
)


@pytest.mark.parametrize("observations", [False, True])
def test_server_body_observations_preserve_eof_and_compact_summary(*, observations: bool) -> None:
    body, state, summary = asyncio.run(asyncio.wait_for(completed_exchange(observations=observations), timeout=5))
    assert body == bytes(range(256)) * (BODY_BYTES // 256)
    assert "streams" not in summary
    assert {key: value for key, value in state.items() if key != "streams"} == summary
    assert summary["normal_eof_total"] == summary["requests_total"] == 1
    assert summary["normal_disconnected_total"] == summary["unexpected_errors_total"] == 0
    assert summary["active_requests"] == 0
    stream = state["streams"]["normal"]
    assert stream["eof_sent"] is True
    assert stream["bytes_written"] == len(body)
    assert summary["body_observations"]["enabled"] is observations
    delivery = stream["body_delivery"]
    totals = summary["body_delivery_totals"]
    if not observations:
        assert delivery is totals is None
        return
    assert (
        delivery["write_calls"] == delivery["drain_calls"] == delivery["drains_completed"] == BODY_BYTES // WRITE_BYTES
    )
    assert delivery["body_finished_ns"] >= delivery["body_started_ns"] > 0
    assert delivery["write_elapsed_ns"] >= 0
    assert delivery["drain_elapsed_ns"] >= 0
    assert delivery["body_loop_elapsed_ns"] >= delivery["write_elapsed_ns"] + delivery["drain_elapsed_ns"]
    assert delivery["max_transport_buffer_bytes"] >= 0
    assert totals == {
        "streams": 1,
        **{key: value for key, value in delivery.items() if key not in {"body_started_ns", "body_finished_ns"}},
    }


@pytest.mark.parametrize("control", ["body-wait", "held-tail"])
def test_body_observations_retain_control_gates_and_exclude_initial_body_wait(control: str) -> None:
    before, after, body, summary = asyncio.run(asyncio.wait_for(gated_exchange(control), timeout=5))
    assert before["active"] is True
    assert before["eof_sent"] is False
    assert before["body_delivery"]["body_finished_ns"] is None
    if control == "body-wait":
        assert before["bytes_written"] == 0
        assert before["body_delivery"]["body_started_ns"] is None
        assert before["body_delivery"]["write_calls"] == 0
    else:
        assert before["bytes_written"] == WRITE_BYTES
        assert before["body_delivery"]["body_started_ns"] > 0
        assert before["body_delivery"]["drains_completed"] == 1
    assert after["active"] is False
    assert after["released"] is after["eof_sent"] is True
    assert after["bytes_written"] == len(body) == BODY_BYTES
    assert after["body_delivery"]["body_finished_ns"] >= after["body_delivery"]["body_started_ns"]
    assert summary["normal_eof_total"] == 0
    assert summary["body_delivery_totals"]["streams"] == summary["body_delivery_totals"]["write_calls"] == 0


def test_body_observations_finalize_partial_server_work_when_owner_cancels() -> None:
    before, after, owned_tasks = asyncio.run(asyncio.wait_for(cancelled_exchange(), timeout=5))
    assert before["active"] is True
    assert before["body_delivery"]["body_finished_ns"] is None
    assert after["active"] is after["eof_sent"] is False
    assert after["bytes_written"] == WRITE_BYTES
    assert after["body_delivery"]["drains_completed"] == 1
    assert after["body_delivery"]["body_finished_ns"] >= after["body_delivery"]["body_started_ns"]
    assert owned_tasks == 0
