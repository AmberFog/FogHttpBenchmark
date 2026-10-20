__all__ = ("revalidate_attribution_rows",)

import json
from pathlib import Path

from foghttp_benchmark.attribution_evidence import inspect_raw_evidence
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.attribution_aggregation import aggregate_attribution_results, integer
from foghttp_benchmark.streaming.report_values import object_list, object_value


def revalidate_attribution_rows(metadata: JsonObject, rows: list[JsonObject], directory: Path) -> JsonObject:
    status = inspect_raw_evidence(metadata, directory)
    status["aggregates_match"] = False
    if status.get("status") != "ok":
        return status
    cases = object_list(object_value(metadata.get("lifecycle")).get("cases"))
    references = object_list(metadata.get("raw_evidence"))
    case_by_sequence = {integer(case.get("sequence")): case for case in cases}
    if len(case_by_sequence) != len(cases) or {integer(item.get("sequence")) for item in references} != set(
        case_by_sequence,
    ):
        return {**status, "status": "invalid", "errors": ["Raw evidence does not match declared fresh cases"]}
    groups: dict[tuple[str, ...], list[JsonObject]] = {}
    for reference in references:
        case = case_by_sequence[integer(reference.get("sequence"))]
        key = tuple(str(case.get(field)) for field in ("mode", "client", "case", "concurrency"))
        groups.setdefault(key, []).append(reference)
    rebuilt: list[JsonObject] = []
    try:
        for group in groups.values():
            # One cell at a time retains at most three bounded fresh-repeat sidecars.
            results = [
                object_value(json.loads((directory / str(item["path"])).read_text())).get("result") for item in group
            ]
            rebuilt.extend(
                aggregate_attribution_results(
                    [object_value(result) for result in results],
                    object_value(metadata.get("conditions")),
                ),
            )
    except (OSError, TypeError, ValueError) as exc:
        return {**status, "status": "invalid", "errors": [f"Raw aggregate recomputation failed: {type(exc).__name__}"]}
    fields = ("mode", "client", "case", "concurrency", "condition_fingerprint")
    equal = sorted(rebuilt, key=lambda row: tuple(str(row.get(field)) for field in fields)) == sorted(
        rows,
        key=lambda row: tuple(str(row.get(field)) for field in fields),
    )
    return {
        **status,
        "status": "ok" if equal else "invalid",
        "aggregates_match": equal,
        "errors": [] if equal else ["Stored aggregate differs from raw per-stream/per-PID evidence"],
    }
