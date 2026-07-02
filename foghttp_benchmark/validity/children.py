__all__ = ("child_process_reasons",)

from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import int_field, str_field, validity_reason
from foghttp_benchmark.validity.models import ValidityReason


def child_process_reasons(metadata: JsonObject) -> list[ValidityReason]:
    isolation = metadata.get("isolation")
    if not isinstance(isolation, dict):
        return []
    children = isolation.get("children")
    if not isinstance(children, list):
        return []

    reasons: list[ValidityReason] = []
    for item in children:
        if not isinstance(item, dict):
            continue
        child = cast("JsonObject", item)
        returncode = int_field(child, "returncode")
        report_path = child.get("report_path")
        if returncode == 0 and isinstance(report_path, str) and report_path:
            continue
        reasons.append(
            validity_reason(
                status="invalid",
                code="isolated_child_failed",
                message="Isolated child process failed or did not write a report.",
                row=child_reference(child),
            ),
        )
    return reasons


def child_reference(child: JsonObject) -> JsonObject:
    return {
        "sequence": int_field(child, "sequence"),
        "client": str_field(child, "client"),
        "scenario": str_field(child, "scenario", "-"),
        "returncode": int_field(child, "returncode"),
    }
