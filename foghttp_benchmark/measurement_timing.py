__all__ = (
    "TimingScope",
    "current_timing_scope",
    "report_timing_scope",
    "validate_row_scopes",
    "validate_timing_compatibility",
)

from enum import StrEnum

from foghttp_benchmark.constants import RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.streaming_profiles import uses_streaming_profile


class TimingScope(StrEnum):
    REQUESTS = "requests-load-only-v2"
    ONE_UPSTREAM = "one-upstream-load-only-v2"
    PROXY_CONNECT = "proxy-connect-load-only-v2"
    RESOURCE_BACKPRESSURE = "resource-backpressure-load-only-v2"
    CLIENT_CREATION = "client-creation-operation-v1"
    REQUEST_BUILDER = "request-builder-load-only-v1"
    STREAMING = "load-only-v2"
    LIFECYCLE = "lifecycle-round-load-v1"
    ASYNC_BYTES = "load-only-incremental-sha256-v1"
    LEGACY_REQUESTS = "requests-sampler-inclusive-v1"
    LEGACY_ONE_UPSTREAM = "one-upstream-sampler-inclusive-v1"
    LEGACY_PROXY_CONNECT = "proxy-connect-sampler-inclusive-v1"
    LEGACY_RESOURCE_BACKPRESSURE = "resource-backpressure-sampler-inclusive-v1"
    LEGACY_STREAMING = "legacy-sampler-v1"


CURRENT_SCOPES = {
    "requests": TimingScope.REQUESTS,
    "compressed-response": TimingScope.REQUESTS,
    "one-upstream": TimingScope.ONE_UPSTREAM,
    "proxy-connect": TimingScope.PROXY_CONNECT,
    "resource-backpressure": TimingScope.RESOURCE_BACKPRESSURE,
    "client-creation": TimingScope.CLIENT_CREATION,
    "request-builder": TimingScope.REQUEST_BUILDER,
    RESPONSE_STREAMING_SUITE: TimingScope.STREAMING,
}
LEGACY_SCOPES = {
    "requests": TimingScope.LEGACY_REQUESTS,
    "compressed-response": TimingScope.LEGACY_REQUESTS,
    "one-upstream": TimingScope.LEGACY_ONE_UPSTREAM,
    "proxy-connect": TimingScope.LEGACY_PROXY_CONNECT,
    "resource-backpressure": TimingScope.LEGACY_RESOURCE_BACKPRESSURE,
    RESPONSE_STREAMING_SUITE: TimingScope.LEGACY_STREAMING,
}
STREAMING_PROFILES = {"lifecycle": TimingScope.LIFECYCLE, "async-bytes": TimingScope.ASYNC_BYTES}


def current_timing_scope(suite: str, profile: str = "default") -> TimingScope:
    if suite == RESPONSE_STREAMING_SUITE and profile != "default":
        scope = STREAMING_PROFILES.get(profile)
    else:
        scope = CURRENT_SCOPES.get(suite)
    if scope is None:
        msg = f"Unknown timing scope for suite={suite!r}, profile={profile!r}"
        raise ValueError(msg)
    return scope


def report_timing_scope(
    suite: str,
    metadata: JsonObject,
    rows: list[JsonObject],
    *,
    runs: list[JsonObject] | None = None,
) -> TimingScope:
    profile = report_profile(suite, metadata, rows)
    current = current_timing_scope(suite, profile)
    supported = {current}
    if profile == "default" and suite in LEGACY_SCOPES:
        supported.add(LEGACY_SCOPES[suite])
    declared = metadata.get("timing_scope")
    if declared is None and suite == RESPONSE_STREAMING_SUITE and profile == "default" and rows:
        declared = rows[0].get("timing_scope")
        if any("timing_scope" not in row for row in rows):
            declared = None
    try:
        scope = TimingScope(declared) if isinstance(declared, str) else None
    except ValueError:
        scope = None
    if scope is None or scope not in supported:
        msg = f"Unknown or unsupported timing scope for suite={suite!r}: {declared!r}"
        raise ValueError(msg)
    validate_row_scopes(scope, rows)
    if runs is not None:
        validate_row_scopes(scope, runs)
    if suite == RESPONSE_STREAMING_SUITE and "timing_scopes" in metadata:
        scopes = metadata["timing_scopes"]
        if scopes != [scope.value] and not (not rows and scopes == []):
            msg = "Report timing scopes disagree with its declared timing scope"
            raise ValueError(msg)
    return scope


def report_profile(suite: str, metadata: JsonObject, rows: list[JsonObject]) -> str:
    if suite == RESPONSE_STREAMING_SUITE:
        if uses_streaming_profile(metadata, rows, "async-bytes"):
            return "async-bytes"
        if uses_streaming_profile(metadata, rows, "lifecycle"):
            return "lifecycle"
    return "default"


def validate_row_scopes(scope: str, rows: list[JsonObject]) -> None:
    declared_rows = [row for row in rows if "timing_scope" in row]
    if declared_rows and (
        len(declared_rows) != len(rows) or any(row["timing_scope"] != scope for row in declared_rows)
    ):
        msg = "Report rows disagree on timing scope"
        raise ValueError(msg)


def validate_timing_compatibility(
    suite: str,
    old_metadata: JsonObject,
    old_rows: list[JsonObject],
    new_metadata: JsonObject,
    new_rows: list[JsonObject],
    *,
    old_runs: list[JsonObject] | None = None,
    new_runs: list[JsonObject] | None = None,
) -> None:
    old_scope = report_timing_scope(suite, old_metadata, old_rows, runs=old_runs)
    new_scope = report_timing_scope(suite, new_metadata, new_rows, runs=new_runs)
    if old_scope != new_scope:
        msg = f"Report timing scopes differ: old={old_scope.value}, new={new_scope.value}"
        raise ValueError(msg)
