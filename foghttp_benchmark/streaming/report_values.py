__all__ = ("int_value", "list_value", "number", "object_list", "object_value")

import math
from typing import cast

from foghttp_benchmark.models import JsonObject


def object_value(value: object) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[JsonObject]:
    return [cast("JsonObject", item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def number(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def int_value(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
