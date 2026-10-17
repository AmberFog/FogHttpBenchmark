import pytest

from foghttp_benchmark.streaming.lifecycle_controls import control_json
from tests.streaming.lifecycle_support import CONTROL_BODY_BYTES, IDLE_CONNECTIONS, quiet_case, run_control_case


@pytest.mark.parametrize("client_name", ["foghttp", "httpx"])
@pytest.mark.parametrize("concurrency", [1, 10])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_controls_prove_held_tail_cancel_settlement_and_eof_recovery(
    client_name: str,
    concurrency: int,
    mode: str,
) -> None:
    result = run_control_case(client_name, concurrency, mode)
    assert result["held_tail"]["status"] == "ok"
    assert result["held_tail"]["expected_aborts"] == concurrency
    assert result["held_tail"]["contexts_closed_before_release"] is True
    assert all(not state["eof_sent"] for state in result["held_tail"]["state_before_release"])
    assert result["recovery"]["bytes_read_total"] == CONTROL_BODY_BYTES * concurrency
    for name in ("body_wait_cancel", "slow_consumer_cancel"):
        control = result[name]
        assert control["status"] == ("ok" if mode == "async" else "unsupported")
        if mode == "async":
            assert control["owned_workers_cancelled_and_awaited"] == concurrency
            assert control["recovery"]["bytes_read_total"] == CONTROL_BODY_BYTES * concurrency


def test_control_origin_rejects_non_loopback() -> None:
    with pytest.raises(ValueError, match="loopback"):
        control_json("http://example.com:80", "/state")


def test_quiet_state_allows_idle_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    result = quiet_case(monkeypatch)
    assert result["status"] == "ok"
    assert result["client_stats"]["active_connections"] == IDLE_CONNECTIONS


def test_quiet_state_rejects_active_nonidle_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TimeoutError, match="did not settle"):
        quiet_case(monkeypatch, idle_connections=2)
