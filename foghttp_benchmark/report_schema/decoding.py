__all__ = ("decode_report_payload", "load_report", "report_suite")

import json
import math
from pathlib import Path

from foghttp_benchmark.measurement_timing import validate_row_scopes
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_schema.fields import (
    require_integer,
    require_number,
    require_object,
    require_rows,
    require_string,
)
from foghttp_benchmark.report_schema.identity import validate_unique_aggregate_rows
from foghttp_benchmark.report_schema.models import REPORT_SCHEMA_VERSION, REPORT_SUITES, DecodedReport
from foghttp_benchmark.report_schema.ordinary import validate_ordinary_rows
from foghttp_benchmark.report_schema.resources import validate_ordinary_resource_coverage, validate_resource_coverage
from foghttp_benchmark.resource_metrics import RESOURCE_METRIC_SCHEMA_VERSION
from foghttp_benchmark.streaming.attribution_validation import revalidate_attribution_rows
from foghttp_benchmark.validity.serialization import validity_summary_from_payload
from foghttp_benchmark.validity.streaming_profiles import uses_streaming_profile


def load_report(path: Path, *, expected_suite: str | None = None) -> DecodedReport:
    try:
        report = decode_report_payload(json.loads(path.read_text()), expected_suite=expected_suite)
        if uses_streaming_profile(report.metadata, report.aggregate_rows, "async-bytes"):
            report.metadata["raw_evidence_validation"] = revalidate_attribution_rows(
                report.metadata,
                report.aggregate_rows,
                path.parent,
            )
    except (TypeError, ValueError) as exc:
        msg = f"{path}: {exc}"
        raise ValueError(msg) from exc
    return report


def decode_report_payload(value: object, *, expected_suite: str | None = None) -> DecodedReport:
    payload = require_object(value, "report")
    validate_finite_json(payload, "report")
    metadata = dict(require_object(payload.get("metadata"), "metadata"))
    aggregate = [dict(row) for row in require_rows(payload.get("aggregate"), "aggregate")]
    runs = [dict(row) for row in require_rows(payload.get("runs"), "runs")]
    if "report_schema_version" in metadata and "suite" not in metadata:
        msg = "metadata.suite is required by report_schema_version"
        raise ValueError(msg)
    suite = report_suite(metadata, aggregate)
    if expected_suite is not None and suite != expected_suite:
        msg = f"metadata.suite {suite!r} does not match parent suite {expected_suite!r}"
        raise ValueError(msg)
    metadata["suite"] = suite
    validate_metadata(metadata, suite)
    validate_isolation_metadata(metadata)
    if "report_schema_version" not in metadata:
        migrate_legacy_rows(suite, aggregate, "aggregate")
        migrate_legacy_rows(suite, runs, "runs")
    research = suite == "response-streaming" and any(
        uses_streaming_profile(metadata, aggregate, profile) for profile in ("lifecycle", "async-bytes")
    )
    if research:
        validate_research_rows(aggregate)
    else:
        validate_layout_markers(suite, aggregate, "aggregate")
        validate_layout_markers(suite, runs, "runs")
        validate_ordinary_rows(suite, aggregate, runs)
        declared_scope = metadata.get("timing_scope")
        if isinstance(declared_scope, str):
            validate_row_scopes(declared_scope, aggregate)
            validate_row_scopes(declared_scope, runs)
        validate_ordinary_resource_coverage(
            suite,
            aggregate,
            runs,
            current=metadata.get("resource_metric_schema_version") == RESOURCE_METRIC_SCHEMA_VERSION,
        )
    if "validity" in metadata:
        validity_summary_from_payload(require_object(metadata["validity"], "metadata.validity"))
    validate_unique_aggregate_rows(suite, aggregate)
    return DecodedReport(suite, metadata, aggregate, runs)


def report_suite(metadata: JsonObject, rows: list[JsonObject]) -> str:
    if "suite" in metadata:
        suite = require_string(metadata["suite"], "metadata.suite")
        if suite not in REPORT_SUITES:
            msg = f"metadata.suite is unsupported: {suite!r}"
            raise ValueError(msg)
        return suite
    inferred = {legacy_row_suite(row) for row in rows}
    if len(inferred) != 1:
        msg = "metadata.suite is required for empty, mixed or ambiguous legacy layouts"
        raise ValueError(msg)
    return inferred.pop()


def legacy_row_suite(row: JsonObject) -> str:
    candidates = row_layouts(row)
    if len(candidates) != 1:
        msg = "metadata.suite cannot be inferred from an unknown or ambiguous legacy row"
        raise ValueError(msg)
    return candidates[0]


def row_layouts(row: JsonObject, *, run: bool = False) -> list[str]:
    operations = "operations_per_second" if run else "ops_s_median"
    requests = "ok_requests_per_second" if run else "ok_req_s_median"
    streams = "ok_streams_per_second" if run else "ok_streams_s_median"
    signatures = {
        "requests": "scenario" in row and requests in row,
        "client-creation": "client_count" in row and operations in row,
        "resource-backpressure": "max_pending_requests" in row,
        "one-upstream": "profile" in row and "case" in row and requests in row,
        "request-builder": "kind" in row and operations in row,
        "response-streaming": streams in row or "verified_bytes_s_median" in row,
        "proxy-connect": "target_scheme" in row and "config" in row,
    }
    return [suite for suite, matches in signatures.items() if matches]


def validate_layout_markers(suite: str, rows: list[JsonObject], path: str) -> None:
    layout = "requests" if suite == "compressed-response" else suite
    for index, row in enumerate(rows):
        if "schema_version" in row:
            msg = f"{path}[{index}].schema_version is reserved for async-bytes rows"
            raise ValueError(msg)
        markers = set(row_layouts(row))
        if path == "runs":
            markers.update(row_layouts(row, run=True))
        foreign = sorted(candidate for candidate in markers if candidate != layout)
        if foreign:
            msg = f"{path}[{index}] contains incompatible layout markers for {suite}: {', '.join(foreign)}"
            raise ValueError(msg)


def migrate_legacy_rows(suite: str, rows: list[JsonObject], path: str) -> None:
    for index, row in enumerate(rows):
        if "max_connections" in row:
            old = require_integer(row["max_connections"], f"{path}[{index}].max_connections")
            if "request_limit" in row and row["request_limit"] != old:
                msg = f"{path}[{index}].request_limit disagrees with max_connections"
                raise ValueError(msg)
            row.setdefault("request_limit", old)
        if suite == "response-streaming" and row.get("profile") not in {"lifecycle", "async-bytes"}:
            row.setdefault("read", "bytes")


def validate_metadata(metadata: JsonObject, suite: str) -> None:
    validate_versions(metadata, suite)
    validate_metadata_objects(metadata)
    args = require_object(metadata.get("args", {}), "metadata.args")
    if "suite" in args and args["suite"] != suite:
        msg = "metadata.args.suite disagrees with metadata.suite"
        raise ValueError(msg)
    if suite != "response-streaming" and "profile" in metadata:
        msg = "metadata.profile is reserved for response-streaming reports"
        raise ValueError(msg)


def validate_versions(metadata: JsonObject, suite: str) -> None:
    if "report_schema_version" in metadata:
        version = require_integer(metadata["report_schema_version"], "metadata.report_schema_version", minimum=1)
        if version != REPORT_SCHEMA_VERSION:
            msg = f"metadata.report_schema_version is unsupported: {version}"
            raise ValueError(msg)
    for key, supported in (
        ("resource_metric_schema_version", RESOURCE_METRIC_SCHEMA_VERSION),
        ("streaming_metric_schema_version", 2),
    ):
        if key in metadata:
            version = require_integer(metadata[key], f"metadata.{key}", minimum=1)
            if version != supported or (key == "streaming_metric_schema_version" and suite != "response-streaming"):
                msg = f"metadata.{key} is unsupported for {suite}: {version}"
                raise ValueError(msg)
    if "schema_version" in metadata and (
        suite != "response-streaming" or not uses_streaming_profile(metadata, [], "async-bytes")
    ):
        msg = "metadata.schema_version is reserved for async-bytes reports"
        raise ValueError(msg)


def validate_metadata_objects(metadata: JsonObject) -> None:
    for key in ("timestamp", "python", "platform"):
        if key in metadata:
            require_string(metadata[key], f"metadata.{key}")
    for key in ("args", "package_versions", "package_sources", "skipped"):
        if key in metadata:
            record = require_object(metadata[key], f"metadata.{key}")
            if key == "package_versions":
                for name, package_version in record.items():
                    require_string(package_version, f"metadata.package_versions.{name}")


def validate_isolation_metadata(metadata: JsonObject) -> None:
    if "isolation" not in metadata:
        return
    isolation = require_object(metadata["isolation"], "metadata.isolation")
    if "children" not in isolation:
        return
    children = require_rows(isolation["children"], "metadata.isolation.children")
    if "child_count" in isolation:
        count = require_integer(isolation["child_count"], "metadata.isolation.child_count")
        if count != len(children):
            msg = "metadata.isolation.child_count must match children"
            raise ValueError(msg)
    research = isolation.get("mode") == "per-lifecycle-case"
    for index, child in enumerate(children):
        validate_child_diagnostic(child, f"metadata.isolation.children[{index}]", research=research)


def validate_child_diagnostic(child: JsonObject, path: str, *, research: bool) -> None:
    for field in ("returncode", "server_returncode"):
        if field == "server_returncode" and field not in child:
            continue
        value = child.get(field)
        if research and value is None:
            continue
        if type(value) is not int:
            msg = f"{path}.{field} must be an integer" + (" or null for a research failure" if research else "")
            raise TypeError(msg)
    if child.get("report_path") is not None:
        require_string(child["report_path"], f"{path}.report_path")
    if "sequence" in child:
        require_integer(child["sequence"], f"{path}.sequence", minimum=1)
    if "duration_s" in child:
        require_number(child["duration_s"], f"{path}.duration_s")
    if "validity" in child:
        validity_summary_from_payload(require_object(child["validity"], f"{path}.validity"))


def validate_research_rows(rows: list[JsonObject]) -> None:
    for index, row in enumerate(rows):
        path = f"aggregate[{index}]"
        for key in ("mode", "client", "case", "read", "consume"):
            require_string(row.get(key), f"{path}.{key}")
        for key in ("concurrency", "request_limit"):
            require_integer(row.get(key), f"{path}.{key}", minimum=1)
        for key in ("errors_total", "warmup_errors_total"):
            require_integer(row.get(key), f"{path}.{key}")
        for key in ("verified_bytes_s_median", "ok_streams_s_median", "p95_ms_median", "p99_ms_median"):
            if row.get(key) is not None:
                require_number(row[key], f"{path}.{key}")
        resources = require_object(row.get("resources", {}), f"{path}.resources")
        for role in ("client", "server"):
            if role in resources:
                observation = require_object(resources[role], f"{path}.resources.{role}")
                validate_resource_coverage(observation, f"{path}.resources.{role}", current=False)


def validate_finite_json(value: object, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        msg = f"{path} must not contain a non-finite JSON number"
        raise ValueError(msg)
    if isinstance(value, dict):
        for key, item in value.items():
            validate_finite_json(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_finite_json(item, f"{path}[{index}]")
