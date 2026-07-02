import pytest

from foghttp_benchmark.isolation.config import (
    CHILD_PROCESS_COOLDOWN_ENV,
    DEFAULT_CHILD_PROCESS_COOLDOWN_S,
    child_process_cooldown_s,
)


CUSTOM_COOLDOWN_S = 30.5


def test_child_process_cooldown_uses_default() -> None:
    assert child_process_cooldown_s({}) == DEFAULT_CHILD_PROCESS_COOLDOWN_S


def test_child_process_cooldown_accepts_positive_env_value() -> None:
    assert child_process_cooldown_s({CHILD_PROCESS_COOLDOWN_ENV: str(CUSTOM_COOLDOWN_S)}) == CUSTOM_COOLDOWN_S


@pytest.mark.parametrize("raw_value", ["0", "-1", "soon"])
def test_child_process_cooldown_rejects_invalid_env_value(raw_value: str) -> None:
    with pytest.raises(ValueError, match=CHILD_PROCESS_COOLDOWN_ENV):
        child_process_cooldown_s({CHILD_PROCESS_COOLDOWN_ENV: raw_value})
