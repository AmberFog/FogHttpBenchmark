import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from foghttp_benchmark.isolation import lifecycle


@pytest.mark.parametrize("missing_at", ["stat", "read_text"])
def test_temporarily_missing_marker_waits_for_next_poll_without_acknowledging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_at: str,
) -> None:
    marker = tmp_path / "marker.json"
    lifecycle.write_object(marker, {"sequence": 1, "phase": "before-load"})
    sampler = Mock()
    sampler.mark.return_value = []
    original = getattr(Path, missing_at)
    disappear = True

    def read_snapshot(path: Path, *args: object, **kwargs: object) -> object:
        nonlocal disappear
        if path == marker and disappear:
            disappear = False
            raise FileNotFoundError(marker)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, missing_at, read_snapshot)

    assert lifecycle.check_marker(tmp_path, sampler, 0) == (0, [])
    sampler.mark.assert_not_called()
    assert not (tmp_path / "ack.json").exists()

    assert lifecycle.check_marker(tmp_path, sampler, 0) == (1, [])
    sampler.mark.assert_called_once_with({"sequence": 1, "phase": "before-load"})
    assert json.loads((tmp_path / "ack.json").read_text()) == {"sequence": 1}


@pytest.mark.parametrize("failure", ["malformed", "permission", "sequence"])
def test_marker_read_failures_other_than_absence_do_not_ack_or_disappear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    marker = tmp_path / "marker.json"
    sampler = Mock()
    if failure == "malformed":
        marker.write_text("{")
        expected = json.JSONDecodeError
    elif failure == "sequence":
        lifecycle.write_object(marker, {"sequence": 2, "phase": "before-load"})
        expected = ValueError
    else:
        monkeypatch.setattr(lifecycle, "read_object", Mock(side_effect=PermissionError("denied")))
        expected = PermissionError

    with pytest.raises(expected):
        lifecycle.check_marker(tmp_path, sampler, 0)

    sampler.mark.assert_not_called()
    assert not (tmp_path / "ack.json").exists()
