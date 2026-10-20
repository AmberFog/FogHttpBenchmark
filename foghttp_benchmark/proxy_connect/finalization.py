__all__ = ("AmbiguousDirectBaselineError", "finalize_proxy_connect_rows")

from foghttp_benchmark.constants import PROXY_CONNECT_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_schema.identity import validate_unique_aggregate_rows


class AmbiguousDirectBaselineError(ValueError):
    """More than one direct aggregate can supply the same proxy comparison baseline."""


def finalize_proxy_connect_rows(rows: list[JsonObject]) -> list[JsonObject]:
    validate_unique_aggregate_rows(PROXY_CONNECT_SUITE, rows)
    baselines: dict[tuple[str, str, str, int], float | None] = {}
    baseline_sources: dict[tuple[str, str, str, int], int] = {}
    for index, row in enumerate(rows):
        if row.get("config") != "direct" or row.get("lifecycle") != "reused-client":
            continue
        key = baseline_key(row)
        if key in baseline_sources:
            msg = f"Ambiguous direct baseline {key!r} at aggregate[{baseline_sources[key]}] and aggregate[{index}]"
            raise AmbiguousDirectBaselineError(msg)
        baseline_sources[key] = index
        value = row.get("ok_req_s_median")
        baselines[key] = float(value) if isinstance(value, int | float) else None

    return [
        {**row, "direct_ratio": direct_ratio(row.get("ok_req_s_median"), baselines.get(baseline_key(row)))}
        for row in rows
    ]


def baseline_key(row: JsonObject) -> tuple[str, str, str, int]:
    return (
        str(row.get("mode", "")),
        str(row.get("client", "")),
        str(row.get("target_scheme", "")),
        int_value(row.get("concurrency")),
    )


def direct_ratio(value: object, baseline: float | None) -> float | None:
    if not isinstance(value, int | float) or baseline is None or baseline <= 0:
        return None
    return float(value) / baseline


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
