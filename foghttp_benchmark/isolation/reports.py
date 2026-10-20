__all__ = ("ReportFinalizationError", "write_isolation_report")

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import platform
import sys
import time
from typing import cast

from foghttp_benchmark.isolation.models import PER_CLIENT_SCENARIO_ISOLATION, ChildProcessResult
from foghttp_benchmark.measurement_timing import report_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.rendering import IsolationRenderContext, load_report_template, render_isolation_markdown
from foghttp_benchmark.report_finalization import MergedReportFinalizer, MergedSuiteReport
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.report_schema.decoding import decode_report_payload, load_report
from foghttp_benchmark.report_schema.identity import aggregate_identity, validate_unique_aggregate_rows
from foghttp_benchmark.reports import package_versions
from foghttp_benchmark.resource_metrics import RESOURCE_METRIC_SCHEMA_VERSION
from foghttp_benchmark.validity.classification import combine_validity_summaries, validity_summary_from_metadata
from foghttp_benchmark.validity.reports import metadata_with_validity
from foghttp_benchmark.validity.serialization import validity_payload, validity_summary_from_payload


def write_isolation_report(
    args: BenchmarkArgs,
    child_results: list[ChildProcessResult],
    skipped: dict[str, str],
    *,
    child_cooldown_s: float,
    finalizer: MergedReportFinalizer,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    child_payloads = load_successful_child_payloads(child_results, expected_suite=args.suite)
    metadata = build_metadata(
        args=args,
        timestamp=timestamp,
        child_results=child_results,
        child_payloads=child_payloads,
        skipped=merge_skipped(skipped, child_payloads),
        child_cooldown_s=child_cooldown_s,
    )
    aggregate_rows = merge_payload_lists(child_payloads, "aggregate")
    run_rows = merge_payload_lists(child_payloads, "runs")
    child_validities = [
        validity_summary_from_metadata(
            report_metadata(payload),
            args.suite,
            merge_payload_lists([payload], "aggregate"),
        )
        for payload in child_payloads
    ]
    finalized = finalize_merged_data(args.suite, metadata, aggregate_rows, child_payloads, finalizer)
    aggregate_rows = finalized.aggregate_rows
    metadata.update(finalized.metadata)
    decode_report_payload(
        {"metadata": metadata, "aggregate": aggregate_rows, "runs": run_rows},
        expected_suite=args.suite,
    )
    metadata = metadata_with_validity(metadata, aggregate_rows)
    metadata["validity"] = validity_payload(
        combine_validity_summaries(
            [
                validity_summary_from_payload(cast("JsonObject", metadata["validity"])),
                *child_validities,
            ],
        ),
    )
    payload: dict[str, object] = {
        "metadata": metadata,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    markdown = render_isolation_markdown(
        load_report_template("isolation_report.md.j2"),
        IsolationRenderContext(
            timestamp=timestamp,
            args=args,
            aggregate=aggregate_rows,
            child_rows=[child_result_markdown_row(result) for result in child_results],
            run_count=len(run_rows),
            unit=isolation_unit(args),
            validity=metadata["validity"],
        ),
    )
    publish_report(output_dir, timestamp, payload, markdown)


class ReportFinalizationError(ValueError):
    pass


def finalize_merged_data(
    suite: str,
    metadata: JsonObject,
    rows: list[JsonObject],
    child_payloads: list[JsonObject],
    finalizer: MergedReportFinalizer,
) -> MergedSuiteReport:
    identities = [aggregate_identity(suite, row) for row in rows]
    result = finalizer(deepcopy(rows), deepcopy([report_metadata(payload) for payload in child_payloads]))
    validate_unique_aggregate_rows(suite, result.aggregate_rows)
    if [aggregate_identity(suite, row) for row in result.aggregate_rows] != identities:
        msg = "Suite finalization must preserve aggregate identities and order"
        raise ReportFinalizationError(msg)
    reserved = metadata.keys() | {
        "validity",
        "report_schema_version",
        "research_provenance",
        "package_sources",
        "timing_scope",
        "resource_metric_schema_version",
        "run_settling",
    }
    conflicts = sorted(result.metadata.keys() & reserved)
    if conflicts:
        msg = f"Suite finalization cannot replace common metadata: {', '.join(conflicts)}"
        raise ReportFinalizationError(msg)
    return result


def load_successful_child_payloads(
    child_results: list[ChildProcessResult],
    *,
    expected_suite: str,
) -> list[JsonObject]:
    payloads: list[JsonObject] = []
    aggregate_rows: list[JsonObject] = []
    sources: list[str] = []
    for result in child_results:
        if result.returncode != 0 or result.report_path is None:
            continue
        report = load_report(Path(result.report_path), expected_suite=expected_suite)
        payloads.append({"metadata": report.metadata, "aggregate": report.aggregate_rows, "runs": report.run_rows})
        aggregate_rows.extend(report.aggregate_rows)
        sources.extend(f"{result.report_path}:aggregate[{index}]" for index in range(len(report.aggregate_rows)))
    validate_unique_aggregate_rows(expected_suite, aggregate_rows, sources=sources)
    return payloads


def build_metadata(
    *,
    args: BenchmarkArgs,
    timestamp: str,
    child_results: list[ChildProcessResult],
    child_payloads: list[JsonObject],
    skipped: dict[str, str],
    child_cooldown_s: float,
) -> JsonObject:
    first_metadata = report_metadata(child_payloads[0]) if child_payloads else {}
    server = first_metadata.get("server", "isolated child benchmark processes")
    versions = first_metadata.get("package_versions")
    if not isinstance(versions, dict):
        versions = package_versions()
    metadata: JsonObject = {
        "timestamp": timestamp,
        "python": sys.version,
        "platform": platform.platform(),
        "server": server,
        "suite": args.suite,
        "args": vars(args),
        "package_versions": versions,
        "skipped": skipped,
        "isolation": {
            "mode": args.isolation,
            "backend": "subprocess",
            "scheduler": "sequential",
            "unit": isolation_unit(args),
            "child_cooldown_s": child_cooldown_s,
            "child_count": len(child_results),
            "children": child_diagnostics(child_results, child_payloads),
        },
    }
    if child_payloads:
        metadata["timing_scope"] = merged_timing_scope(args.suite, child_payloads)
        if all(
            report_metadata(payload).get("resource_metric_schema_version") == RESOURCE_METRIC_SCHEMA_VERSION
            for payload in child_payloads
        ):
            metadata["resource_metric_schema_version"] = RESOURCE_METRIC_SCHEMA_VERSION
    for key in ("package_sources", "research_provenance"):
        for payload in child_payloads:
            child_metadata = payload.get("metadata")
            if isinstance(child_metadata, dict) and key in child_metadata:
                metadata[key] = child_metadata[key]
                break
    run_settling = first_metadata.get("run_settling")
    if isinstance(run_settling, dict):
        metadata["run_settling"] = run_settling
    return metadata


def merged_timing_scope(suite: str, child_payloads: list[JsonObject]) -> str:
    scopes = [
        report_timing_scope(
            suite,
            report_metadata(payload),
            merge_payload_lists([payload], "aggregate"),
            runs=merge_payload_lists([payload], "runs"),
        )
        for payload in child_payloads
    ]
    if any(scope != scopes[0] for scope in scopes):
        msg = "Isolated children disagree on timing scope"
        raise ValueError(msg)
    return scopes[0].value


def isolation_unit(args: BenchmarkArgs) -> str:
    if args.isolation == PER_CLIENT_SCENARIO_ISOLATION:
        return "client-scenario"
    return "client"


def report_metadata(payload: JsonObject) -> JsonObject:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return cast("JsonObject", metadata)


def merge_payload_lists(child_payloads: list[JsonObject], key: str) -> list[JsonObject]:
    merged: list[JsonObject] = []
    for payload in child_payloads:
        value = payload.get(key)
        if not isinstance(value, list):
            msg = f"Child report JSON field {key!r} must be a list"
            raise TypeError(msg)
        payload_items: list[JsonObject] = []
        for item in value:
            if not isinstance(item, dict):
                msg = f"Child report JSON field {key!r} must contain objects"
                raise TypeError(msg)
            payload_items.append(cast("JsonObject", item))
        merged.extend(payload_items)
    return merged


def merge_skipped(parent_skipped: dict[str, str], child_payloads: list[JsonObject]) -> dict[str, str]:
    merged = dict(parent_skipped)
    for payload in child_payloads:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            continue
        skipped = metadata.get("skipped")
        if not isinstance(skipped, dict):
            continue
        for key, value in skipped.items():
            merged.setdefault(str(key), str(value))
    return merged


def child_diagnostics(
    child_results: list[ChildProcessResult],
    child_payloads: list[JsonObject],
) -> list[JsonObject]:
    successful_payloads = iter(child_payloads)
    diagnostics: list[JsonObject] = []
    for result in child_results:
        payload = child_result_payload(result)
        if result.returncode == 0 and result.report_path is not None:
            child_metadata = next(successful_payloads).get("metadata")
            if isinstance(child_metadata, dict):
                for key in ("package_sources", "research_provenance", "resource_metric_schema_version", "validity"):
                    if key in child_metadata:
                        payload[key] = child_metadata[key]
        diagnostics.append(payload)
    return diagnostics


def child_result_payload(result: ChildProcessResult) -> JsonObject:
    payload = asdict(result)
    return cast("JsonObject", payload)


def child_result_markdown_row(result: ChildProcessResult) -> str:
    report = "-" if result.report_path is None else Path(result.report_path).parent.as_posix()
    scenario = "-" if result.scenario is None else result.scenario
    return (
        f"| {result.sequence} | `{result.client}` | `{scenario}` | {result.returncode} | {result.duration_s:.2f} | "
        f"{optional_float(result.peaks.rss_mb)} | {optional_int(result.peaks.threads)} | "
        f"{optional_int(result.peaks.fds)} | `{report}` |"
    )


def optional_float(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.1f}"


def optional_int(value: int | None) -> str:
    if value is None:
        return "unavailable"
    return str(value)
