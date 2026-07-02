import asyncio

import pytest

from foghttp_benchmark.run_settling import (
    DEFAULT_RUN_COOLDOWN_OPENED_THRESHOLD,
    DEFAULT_RUN_COOLDOWN_S,
    RUN_COOLDOWN_ENV,
    RUN_COOLDOWN_OPENED_THRESHOLD_ENV,
    RunSettlingConfig,
    run_settling_config,
    settle_after_run,
    should_settle_after_run,
)


CUSTOM_COOLDOWN_S = 1.5
CUSTOM_THRESHOLD = 42


def test_run_settling_config_uses_defaults() -> None:
    config = run_settling_config({})

    assert config == RunSettlingConfig(
        cooldown_s=DEFAULT_RUN_COOLDOWN_S,
        opened_connection_threshold=DEFAULT_RUN_COOLDOWN_OPENED_THRESHOLD,
    )


def test_run_settling_config_accepts_env_values() -> None:
    config = run_settling_config(
        {
            RUN_COOLDOWN_ENV: str(CUSTOM_COOLDOWN_S),
            RUN_COOLDOWN_OPENED_THRESHOLD_ENV: str(CUSTOM_THRESHOLD),
        },
    )

    assert config == RunSettlingConfig(
        cooldown_s=CUSTOM_COOLDOWN_S,
        opened_connection_threshold=CUSTOM_THRESHOLD,
    )


@pytest.mark.parametrize(
    ("env_name", "raw_value"),
    [
        (RUN_COOLDOWN_ENV, "0"),
        (RUN_COOLDOWN_ENV, "-1"),
        (RUN_COOLDOWN_ENV, "soon"),
        (RUN_COOLDOWN_OPENED_THRESHOLD_ENV, "0"),
        (RUN_COOLDOWN_OPENED_THRESHOLD_ENV, "-1"),
        (RUN_COOLDOWN_OPENED_THRESHOLD_ENV, "many"),
    ],
)
def test_run_settling_config_rejects_invalid_env_values(env_name: str, raw_value: str) -> None:
    with pytest.raises(ValueError, match=env_name):
        run_settling_config({env_name: raw_value})


def test_should_settle_after_high_connection_churn() -> None:
    assert should_settle_after_run(
        {"connections_opened": CUSTOM_THRESHOLD},
        RunSettlingConfig(cooldown_s=CUSTOM_COOLDOWN_S, opened_connection_threshold=CUSTOM_THRESHOLD),
    )


def test_should_settle_after_failed_connection_open() -> None:
    assert should_settle_after_run(
        {"connections_open_failed": 1},
        RunSettlingConfig(cooldown_s=CUSTOM_COOLDOWN_S, opened_connection_threshold=CUSTOM_THRESHOLD),
    )


def test_should_not_settle_after_reused_connection_run() -> None:
    assert not should_settle_after_run(
        {"connections_opened": 1},
        RunSettlingConfig(cooldown_s=CUSTOM_COOLDOWN_S, opened_connection_threshold=CUSTOM_THRESHOLD),
    )


def test_settle_after_run_waits_only_for_high_churn(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    config = RunSettlingConfig(cooldown_s=CUSTOM_COOLDOWN_S, opened_connection_threshold=CUSTOM_THRESHOLD)

    asyncio.run(settle_after_run({"connections_opened": 1}, config))
    asyncio.run(settle_after_run({"connections_opened": CUSTOM_THRESHOLD}, config))

    assert sleeps == [CUSTOM_COOLDOWN_S]
