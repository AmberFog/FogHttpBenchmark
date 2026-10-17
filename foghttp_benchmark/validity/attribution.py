__all__ = ("attribution_report_reasons",)

import hashlib
import math
from typing import cast

from foghttp_benchmark.attribution_evidence import (
    ATTRIBUTION_POLICY_VERSION,
    ATTRIBUTION_SCHEMA_VERSION,
    condition_fingerprint,
    harness_fingerprint,
)
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.research_baseline import FOGHTTP_BASELINE
from foghttp_benchmark.validity.helpers import row_reference, validity_reason
from foghttp_benchmark.validity.lifecycle import (
    LIFECYCLE_MIN_VARIATION_REPETITIONS,
    LIFECYCLE_VARIATION_LIMIT_PERCENT,
    aggregate_reasons,
    plan_case_reasons,
)
from foghttp_benchmark.validity.models import ValidityReason, ValidityStatus
from foghttp_benchmark.validity.streaming_profiles import uses_streaming_profile


GIT_SHA_LENGTH = 40


def attribution_report_reasons(metadata: JsonObject, rows: list[JsonObject]) -> list[ValidityReason]:
    if not uses_streaming_profile(metadata, rows, "async-bytes"):
        return []
    reasons: list[ValidityReason] = []
    if (
        metadata.get("schema_version") != ATTRIBUTION_SCHEMA_VERSION
        or metadata.get("policy_version") != ATTRIBUTION_POLICY_VERSION
    ):
        reasons.append(
            reason("invalid", "attribution_schema_missing", "Attribution schema/policy evidence is missing."),
        )
    reasons.extend(fingerprint_reasons(metadata))
    lifecycle = object_value(metadata.get("lifecycle"))
    reasons.extend(plan_case_reasons(lifecycle))
    reasons.extend(aggregate_reasons(rows))
    evidence = object_value(metadata.get("raw_evidence_validation"))
    if (
        evidence.get("status") != "ok"
        or evidence.get("checked") != lifecycle.get("expected_cases")
        or evidence.get("aggregates_match") is not True
    ):
        reasons.append(
            reason(
                "invalid",
                "attribution_raw_evidence_invalid",
                "Raw sidecars are missing, changed or not verified from disk.",
            ),
        )
    provenance = object_value(metadata.get("research_provenance"))
    manifest = object_value(provenance.get("manifest"))
    source = object_value(manifest.get("source"))
    installation = object_value(provenance.get("installation"))
    if (
        not digest(provenance.get("manifest_sha256"))
        or not digest(installation.get("native_sha256"))
        or not git_sha(source.get("sha"))
        or source.get("ref") != FOGHTTP_BASELINE.ref
        or object_value(manifest.get("build")).get("profile") != "release"
    ):
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_provenance_missing",
                "A verified release-wheel research manifest is mandatory for a performance conclusion.",
            ),
        )
    if not rows:
        reasons.append(reason("invalid", "attribution_rows_missing", "No measured attribution cells are present."))
    if harness_fingerprint(metadata) is None:
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_harness_provenance_missing",
                (
                    "Harness commit, tracked diff and complete file fingerprints "
                    "are required for a performance conclusion."
                ),
            ),
        )
    for row in rows:
        reasons.extend(attribution_row_reasons(row))
    return reasons


def attribution_row_reasons(row: JsonObject) -> list[ValidityReason]:
    reasons = fingerprint_reasons(row)
    configuration = object_value(row.get("configuration"))
    if (
        object_value(configuration.get("attribution")).get("minimum_duration_s")
        and row.get("duration_window_complete") is not True
    ):
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_duration_short",
                "A duration window reached its hard stream cap before the declared minimum load time.",
                row,
            ),
        )
    expected = row.get("expected_streams_total")
    verified = row.get("verified_bytes_total")
    payload = configuration.get("body_bytes")
    if (
        type(expected) is not int
        or expected <= 0
        or type(payload) is not int
        or payload <= 0
        or type(verified) is not int
        or verified != expected * payload
        or row.get("complete_streams_total") != expected
        or row.get("stream_samples_total") != expected
        or row.get("integrity_failures_total") != 0
        or row.get("successful_repeats") != row.get("repeats")
        or row.get("stream_measurement_evidence_complete") is not True
        or row.get("declared_workload_complete") is not True
        or row.get("gc_configuration_matches") is not True
        or configuration != object_value(object_value(row.get("conditions")).get("configuration"))
    ):
        reasons.append(
            reason(
                "invalid",
                "attribution_integrity_incomplete",
                (
                    "Every expected stream must have complete EOF, framing, byte count and digest evidence "
                    "before contributing verified bytes."
                ),
                row,
            ),
        )
    if positive_number(row.get("verified_bytes_s_median")) is None:
        reasons.append(
            reason(
                "invalid",
                "attribution_primary_missing",
                "Verified byte throughput is missing or nonpositive.",
                row,
            ),
        )
    if row.get("instrumentation") != "control" or row.get("profiler_label") is not None:
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_diagnostic_only",
                "Diagnostic tracing/profiler runs cannot serve as control measurements.",
                row,
            ),
        )
    if (
        object_value(configuration.get("attribution")).get("profiler") == "cprofile"
        and row.get("python_profile_thread_scope_qualified") is not True
    ):
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_python_profile_unqualified",
                "Interpreter monitoring cannot provide thread-scoped timing or caller attribution.",
                row,
            ),
        )
    if row.get("server_health_complete") is not True:
        reasons.append(
            reason(
                "invalid",
                "attribution_server_health_incomplete",
                "Server health/EOF evidence is missing or failed.",
                row,
            ),
        )
    if row.get("cpu_pid_identity_valid") is not True:
        reasons.append(
            reason(
                "invalid",
                "attribution_cpu_pid_mismatch",
                "CPU observations do not match the owned client and server PIDs.",
                row,
            ),
        )
    if not integer_at_least(row.get("variation_sample_count"), LIFECYCLE_MIN_VARIATION_REPETITIONS):
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_repetitions_insufficient",
                "At least three fresh complete repetitions are required to assess variation.",
                row,
            ),
        )
    variation = positive_number(row.get("verified_bytes_s_cv_percent"), allow_zero=True)
    if variation is None or variation > LIFECYCLE_VARIATION_LIMIT_PERCENT:
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_variation_unqualified",
                "Verified byte throughput variation is missing or exceeds the predeclared 10% criterion.",
                row,
            ),
        )
    reasons.extend(resource_evidence_reasons(row))
    return reasons


def resource_evidence_reasons(row: JsonObject) -> list[ValidityReason]:
    reasons: list[ValidityReason] = []
    for role in ("client", "server"):
        cpu = object_value(object_value(row.get("cpu")).get(role))
        if cpu.get("complete") is not True or any(
            positive_number(cpu.get(key), allow_zero=True) is None
            for key in (
                "user_s_median",
                "system_s_median",
                "total_s_median",
                "cpu_seconds_per_verified_byte_median",
                "cpu_seconds_per_wall_second_median",
            )
        ):
            reasons.append(
                reason(
                    "needs-rerun",
                    "attribution_cpu_incomplete",
                    f"Separate {role} load CPU evidence is unavailable; retained reasons do not replace measurement.",
                    row,
                ),
            )
    overhead = object_value(row.get("overhead"))
    if (
        overhead.get("complete") is not True
        or overhead.get("distribution_complete") is not True
        or any(
            positive_number(overhead.get(key), allow_zero=True) is None
            for key in ("scalar_only_s_median", "sha256_only_s_median", "combined_s_median")
        )
    ):
        reasons.append(
            reason(
                "needs-rerun",
                "attribution_overhead_incomplete",
                "Bounded replay did not qualify hashing/scalar overhead on the complete observed distribution.",
                row,
            ),
        )
    return reasons


def fingerprint_reasons(value: JsonObject) -> list[ValidityReason]:
    conditions = value.get("conditions")
    try:
        valid = isinstance(conditions, dict) and condition_fingerprint(cast("JsonObject", conditions)) == value.get(
            "condition_fingerprint",
        )
    except (TypeError, ValueError):
        valid = False
    return (
        []
        if valid
        else [
            reason(
                "invalid",
                "attribution_conditions_invalid",
                "Measurement conditions or their canonical fingerprint are missing or inconsistent.",
                value,
            ),
        ]
    )


def object_value(value: object) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def positive_number(value: object, *, allow_zero: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value) if value >= 0 and (allow_zero or value > 0) else None


def integer_at_least(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == hashlib.sha256().digest_size * 2
        and all(character in "0123456789abcdef" for character in value)
    )


def git_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == GIT_SHA_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def reason(status: ValidityStatus, code: str, message: str, row: JsonObject | None = None) -> ValidityReason:
    return validity_reason(status=status, code=code, message=message, row=row_reference(row or {}))
