__all__ = (
    "CHILD_PROCESS_COOLDOWN_ENV",
    "DEFAULT_CHILD_PROCESS_COOLDOWN_S",
    "child_process_cooldown_s",
)

from collections.abc import Mapping


CHILD_PROCESS_COOLDOWN_ENV = "FOGHTTP_BENCHMARK_CHILD_COOLDOWN_S"
DEFAULT_CHILD_PROCESS_COOLDOWN_S = 15.0


def child_process_cooldown_s(env: Mapping[str, str]) -> float:
    raw_value = env.get(CHILD_PROCESS_COOLDOWN_ENV)
    if raw_value is None:
        return DEFAULT_CHILD_PROCESS_COOLDOWN_S
    try:
        value = float(raw_value)
    except ValueError as error:
        message = f"{CHILD_PROCESS_COOLDOWN_ENV} must be a positive float"
        raise ValueError(message) from error
    if value <= 0:
        message = f"{CHILD_PROCESS_COOLDOWN_ENV} must be a positive float"
        raise ValueError(message)
    return value
