__all__ = ("streaming_profile_reasons", "uses_streaming_profile")

from typing import Literal

from foghttp_benchmark.constants import RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import row_reference, validity_reason
from foghttp_benchmark.validity.models import ValidityReason


RESEARCH_PROFILES = ("lifecycle", "async-bytes")
ORDINARY_PROFILES = (None, "default")


def uses_streaming_profile(
    metadata: JsonObject,
    rows: list[JsonObject],
    profile: Literal["lifecycle", "async-bytes"],
) -> bool:
    return (
        metadata.get("profile") == profile
        or any(row.get("profile") == profile for row in rows)
        or research_envelope_profile(metadata, rows) == profile
    )


def research_envelope_profile(
    metadata: JsonObject,
    rows: list[JsonObject],
) -> Literal["lifecycle", "async-bytes"] | None:
    for value in (metadata, *rows):
        policy = value.get("policy_version")
        if (
            (isinstance(policy, str) and policy.startswith("async-bytes-"))
            or "raw_evidence" in value
            or "raw_evidence_validation" in value
            or value.get("primary_metric") == "verified_bytes_s_median"
            or "verified_bytes_s_median" in value
        ):
            return "async-bytes"
        conditions = value.get("conditions")
        for configuration in (
            value.get("config"),
            value.get("configuration"),
            conditions.get("configuration") if isinstance(conditions, dict) else None,
        ):
            if isinstance(configuration, dict) and configuration.get("attribution") is not None:
                return "async-bytes"
    isolation = metadata.get("isolation")
    if "lifecycle" in metadata or (isinstance(isolation, dict) and isolation.get("mode") == "per-lifecycle-case"):
        return "lifecycle"
    for row in rows:
        resources = row.get("resources")
        if (
            isinstance(resources, dict)
            and isinstance(resources.get("client"), dict)
            and isinstance(resources.get("server"), dict)
        ):
            return "lifecycle"
    return None


def streaming_profile_reasons(
    suite: str,
    metadata: JsonObject,
    rows: list[JsonObject],
) -> list[ValidityReason]:
    if suite != RESPONSE_STREAMING_SUITE:
        return []
    profile = metadata.get("profile")
    if profile not in (*ORDINARY_PROFILES, *RESEARCH_PROFILES):
        return [
            mismatch_reason("Response-streaming metadata declares an unknown profile.", {}),
        ]
    envelope = research_envelope_profile(metadata, rows)
    if envelope is not None and profile != envelope:
        return [
            mismatch_reason("A research streaming envelope requires its explicit matching metadata profile.", {}),
        ]
    for row in rows:
        row_profile = row.get("profile")
        matches = row_profile == profile if profile in RESEARCH_PROFILES else row_profile in ORDINARY_PROFILES
        if not matches:
            return [
                mismatch_reason(
                    "Response-streaming metadata and every aggregate row must declare the same research profile; "
                    "ordinary legacy rows may omit it.",
                    row_reference(row),
                ),
            ]
    return []


def mismatch_reason(message: str, row: JsonObject) -> ValidityReason:
    return validity_reason(status="invalid", code="streaming_profile_mismatch", message=message, row=row)
