import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from foghttp_benchmark.streaming import lifecycle_worker
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_worker import _Worker


def worker_at(tmp_path: Path) -> _Worker:
    return _Worker(
        LifecycleCase(1, "httpx", "async", "stream-1m", 1, 1),
        LifecycleConfig(settle_timeout_s=0.1),
        "http://127.0.0.1:1",
        tmp_path,
        tmp_path / "client.json",
    )


def test_ack_disappearing_during_read_is_not_accepted_and_next_poll_can_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = worker_at(tmp_path)
    ack = tmp_path / "ack.json"
    ack.write_text(json.dumps({"sequence": 1}))
    original = Path.read_text
    disappear = True

    def read_snapshot(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal disappear
        if path == ack and disappear:
            disappear = False
            raise FileNotFoundError(ack)
        return original(path, *args, **kwargs)

    def pending_poll(_seconds: float) -> None:
        assert worker.phases == []
        assert not worker.output.exists()

    sleep = Mock(side_effect=pending_poll)
    monkeypatch.setattr(Path, "read_text", read_snapshot)
    monkeypatch.setattr(lifecycle_worker.time, "monotonic", Mock(return_value=0.0))
    monkeypatch.setattr(lifecycle_worker.time, "sleep", sleep)

    worker.mark("before-load")

    assert len(worker.phases) == 1
    assert worker.phases[0]["sequence"] == 1
    assert json.loads(worker.output.read_text())["phases"] == worker.phases
    sleep.assert_called_once_with(0.005)


@pytest.mark.parametrize("acknowledgement", [None, {"sequence": 0}, {"sequence": 2}])
def test_missing_or_wrong_ack_retains_original_deadline_and_never_advances_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acknowledgement: dict[str, int] | None,
) -> None:
    worker = worker_at(tmp_path)
    if acknowledgement is not None:
        (tmp_path / "ack.json").write_text(json.dumps(acknowledgement))
    clock = Mock(side_effect=[0.0, 0.05, 0.1])
    sleep = Mock()
    monkeypatch.setattr(lifecycle_worker.time, "monotonic", clock)
    monkeypatch.setattr(lifecycle_worker.time, "sleep", sleep)

    with pytest.raises(TimeoutError, match="did not acknowledge"):
        worker.mark("before-load")

    assert worker.phases == []
    assert not worker.output.exists()
    sleep.assert_called_once_with(0.005)


@pytest.mark.parametrize("failure", ["malformed", "permission"])
def test_ack_corruption_and_access_failure_are_not_retried_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    worker = worker_at(tmp_path)
    ack = tmp_path / "ack.json"
    if failure == "malformed":
        ack.write_text("{")
        expected = json.JSONDecodeError
    else:
        monkeypatch.setattr(Path, "read_text", Mock(side_effect=PermissionError("denied")))
        expected = PermissionError
    sleep = Mock()
    monkeypatch.setattr(lifecycle_worker.time, "sleep", sleep)

    with pytest.raises(expected):
        worker.mark("before-load")

    assert worker.phases == []
    assert not worker.output.exists()
    sleep.assert_not_called()
