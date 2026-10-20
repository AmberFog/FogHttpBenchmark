__all__ = ("require_integer", "require_number", "require_object", "require_rows", "require_string")

import math

from foghttp_benchmark.models import JsonObject


def require_object(value: object, path: str) -> JsonObject:
    if not isinstance(value, dict):
        msg = f"{path} must be an object"
        raise TypeError(msg)
    return value


def require_rows(value: object, path: str) -> list[JsonObject]:
    if not isinstance(value, list):
        msg = f"{path} must be a list of objects"
        raise TypeError(msg)
    return [require_object(item, f"{path}[{index}]") for index, item in enumerate(value)]


def require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = f"{path} must be a nonempty string"
        raise ValueError(msg)
    return value


def require_integer(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        msg = f"{path} must be an integer >= {minimum}"
        raise ValueError(msg)
    return value


def require_number(value: object, path: str, *, minimum: float | None = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{path} must be a finite number"
        raise TypeError(msg)
    try:
        number = float(value)
    except OverflowError as exc:
        msg = f"{path} must be a finite number"
        raise ValueError(msg) from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        msg = f"{path} must be a finite number" + (f" >= {minimum}" if minimum is not None else "")
        raise ValueError(msg)
    return number
