__all__ = ("lifecycle_report_reasons",)

from typing import cast

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import int_field, optional_float_field, row_reference, validity_reason
from foghttp_benchmark.validity.models import ValidityReason
from foghttp_benchmark.validity.streaming_profiles import uses_streaming_profile


LIFECYCLE_VARIATION_LIMIT_PERCENT = 10.0
LIFECYCLE_MIN_VARIATION_REPETITIONS = 3


def lifecycle_report_reasons(metadata: JsonObject, rows: list[JsonObject]) -> list[ValidityReason]:
    if not uses_streaming_profile(metadata, rows, "lifecycle"):
        return []
    lifecycle = metadata.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return [invalid("lifecycle_cases_missing", "Lifecycle process diagnostics are missing.", {})]
    return [*plan_case_reasons(cast("JsonObject", lifecycle)), *aggregate_reasons(rows)]


def plan_case_reasons(lifecycle: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    cases = lifecycle.get("cases")
    if (
        not isinstance(cases, list)
        or len(cases) != lifecycle.get("expected_cases")
        or not lifecycle.get("plan_matches")
    ):
        reasons.append(
            invalid("lifecycle_plan_incomplete", "Lifecycle reports do not match the declared case plan.", {}),
        )
    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict):
            reasons.append(invalid("lifecycle_case_invalid", "Lifecycle process diagnostics are malformed.", {}))
            continue
        reasons.extend(case_reasons(cast("JsonObject", case)))
    if isinstance(cases, list):
        reasons.extend(pid_reuse_reasons([cast("JsonObject", case) for case in cases if isinstance(case, dict)]))
    return reasons


def pid_reuse_reasons(cases: list[JsonObject]) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    seen_owned_pids: set[int] = set()
    for case in cases:
        for role in ("client", "server"):
            pid = case.get(f"{role}_pid")
            if not isinstance(pid, int):
                continue
            if pid in seen_owned_pids:
                reasons.append(
                    invalid(
                        "lifecycle_pid_reused",
                        "A client/server PID appears in multiple fresh cases; ownership is ambiguous.",
                        row_reference(case),
                    ),
                )
            seen_owned_pids.add(pid)
    return reasons


def aggregate_reasons(rows: list[JsonObject]) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    for row in rows:
        if row.get("configurations_match") is not True:
            reasons.append(
                invalid(
                    "lifecycle_configuration_mismatch",
                    "Fresh repetitions used different or missing lifecycle configurations.",
                    row_reference(row),
                ),
            )
        if int_field(row, "variation_sample_count") < LIFECYCLE_MIN_VARIATION_REPETITIONS:
            continue
        for field in ("streams_s_cv_percent", "duration_s_cv_percent"):
            variation = optional_float_field(row, field)
            if variation is not None and variation > LIFECYCLE_VARIATION_LIMIT_PERCENT:
                reasons.append(
                    validity_reason(
                        status="warning",
                        code="lifecycle_high_variation",
                        message=(
                            f"{field} is {variation:.1f}%, above the predeclared 10% criterion "
                            "across fresh repetitions."
                        ),
                        row=row_reference(row),
                    ),
                )
    return reasons


def case_reasons(case: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    reference = row_reference(case)
    if case.get("failure") or case.get("failures") or case.get("worker_status") != "ok" or case.get("errors"):
        reasons.append(
            invalid(
                "lifecycle_case_failed",
                "Lifecycle child, server, resource guard or owned control failed; raw output is retained.",
                reference,
            ),
        )
    if case.get("pid_identity_valid") is not True:
        reasons.append(
            invalid(
                "lifecycle_pid_identity_invalid",
                "Parent/client/server PIDs or per-PID samples do not match the declared ownership.",
                reference,
            ),
        )
    if case.get("resources_truncated") is not False or case.get("resource_samples_present") is not True:
        reasons.append(
            invalid(
                "lifecycle_resource_samples_incomplete",
                "Resource samples are missing or exceeded their bounded recording cap.",
                reference,
            ),
        )
    controls = case.get("controls")
    if not isinstance(controls, dict):
        return [*reasons, invalid("lifecycle_controls_missing", "Lifecycle control outcomes are missing.", reference)]
    for name in ("held_tail", "recovery", "body_wait_cancel", "slow_consumer_cancel"):
        control = controls.get(name)
        status = control.get("status") if isinstance(control, dict) else None
        unsupported_sync = (
            case.get("mode") == "sync"
            and name.endswith("_cancel")
            and status == "unsupported"
            and bool(control.get("reason"))
            if isinstance(control, dict)
            else False
        )
        if status != "ok" and not unsupported_sync:
            reasons.append(
                invalid("lifecycle_control_failed", f"Required lifecycle control {name!r} did not succeed.", reference),
            )
        if (
            name == "held_tail"
            and isinstance(control, dict)
            and int_field(cast("JsonObject", control), "expected_aborts") <= 0
        ):
            reasons.append(
                invalid(
                    "lifecycle_abort_unverified",
                    "Held-tail control did not verify any unread-body abort.",
                    reference,
                ),
            )
    return reasons


def invalid(code: str, message: str, row: JsonObject) -> ValidityReason:
    return validity_reason(status="invalid", code=code, message=message, row=row)
