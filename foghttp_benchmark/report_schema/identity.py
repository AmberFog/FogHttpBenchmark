__all__ = (
    "aggregate_identity",
    "comparison_group",
    "validate_unique_aggregate_rows",
    "validate_unique_identities",
)

from collections.abc import Iterable
import json

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_schema.fields import require_string


IDENTITY_FIELDS = {
    "requests": ("scenario", "concurrency", "request_limit"),
    "compressed-response": ("scenario", "concurrency", "request_limit"),
    "client-creation": ("scenario", "client_count", "iterations"),
    "resource-backpressure": (
        "scenario",
        "concurrency",
        "request_limit",
        "per_origin_request_limit",
        "max_pending_requests",
        "max_buffered_response_bytes",
    ),
    "one-upstream": ("group", "case", "profile", "concurrency", "request_limit"),
    "request-builder": ("kind", "group", "case", "profile", "iterations"),
    "response-streaming": ("case", "read", "consume", "concurrency", "request_limit"),
    "proxy-connect": ("case", "group", "target_scheme", "config", "lifecycle", "concurrency", "request_limit"),
}


def aggregate_identity(suite: str, row: JsonObject) -> tuple[str, ...]:
    """Return a key for a structurally decoded aggregate; never include measurements."""
    fields = IDENTITY_FIELDS.get(suite)
    if fields is None:
        msg = f"Unsupported aggregate identity suite: {suite!r}"
        raise ValueError(msg)
    identity = (
        require_string(row.get("mode"), "mode"),
        require_string(row.get("client"), "client"),
        *("-" if row.get(field) is None else str(row[field]) for field in fields),
    )
    return (*identity, *streaming_dimensions(row)) if suite == "response-streaming" else identity


def streaming_dimensions(row: JsonObject) -> tuple[str, ...]:
    profile = row.get("profile")
    dimensions: tuple[str, ...]
    if profile == "lifecycle":
        dimensions = ("lifecycle", json.dumps(row.get("configuration", {}), sort_keys=True))
    elif profile == "async-bytes":
        dimensions = (
            "async-bytes",
            require_string(row.get("condition_fingerprint"), "condition_fingerprint"),
            require_string(row.get("primary_metric"), "primary_metric"),
        )
    else:
        dimensions = ()
    if "throughput_scope" in row or "timing_scope" in row:
        dimensions = (
            *dimensions,
            require_string(row.get("throughput_scope", "legacy-observed-v1"), "throughput_scope"),
            require_string(row.get("timing_scope", "legacy-sampler-v1"), "timing_scope"),
        )
    return dimensions


def comparison_group(identity: tuple[str, ...]) -> tuple[str, ...]:
    """Keep workload dimensions while removing the client at position one."""
    return (*identity[:1], *identity[2:])


def validate_unique_aggregate_rows(
    suite: str,
    rows: Iterable[JsonObject],
    *,
    sources: Iterable[str] | None = None,
) -> None:
    validate_unique_identities((aggregate_identity(suite, row) for row in rows), sources=sources)


def validate_unique_identities(
    identities: Iterable[tuple[str, ...]],
    *,
    sources: Iterable[str] | None = None,
) -> None:
    seen: dict[tuple[str, ...], str] = {}
    positions = (
        ((identity, f"aggregate[{index}]") for index, identity in enumerate(identities))
        if sources is None
        else zip(identities, sources, strict=True)
    )
    for identity, source in positions:
        if identity in seen:
            msg = f"Duplicate aggregate identity {identity!r} at {seen[identity]} and {source}"
            raise ValueError(msg)
        seen[identity] = source
