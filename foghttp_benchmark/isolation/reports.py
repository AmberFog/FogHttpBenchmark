__all__ = ("write_isolation_report",)

from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys
import time
from typing import cast

from foghttp_benchmark.constants import PROXY_CONNECT_SUITE
from foghttp_benchmark.isolation.models import PER_CLIENT_SCENARIO_ISOLATION, ChildProcessResult
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.reports import package_versions, report_environment


def write_isolation_report(
    args: BenchmarkArgs,
    child_results: list[ChildProcessResult],
    skipped: dict[str, str],
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    child_payloads = load_successful_child_payloads(child_results)
    metadata = build_metadata(
        args=args,
        timestamp=timestamp,
        child_results=child_results,
        child_payloads=child_payloads,
        skipped=merge_skipped(skipped, child_payloads),
    )
    aggregate_rows = normalize_aggregate_rows(args.suite, merge_payload_lists(child_payloads, "aggregate"))
    run_rows = merge_payload_lists(child_payloads, "runs")
    payload: dict[str, object] = {
        "metadata": metadata,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_isolation_markdown(timestamp, args, child_results, payload)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def load_successful_child_payloads(child_results: list[ChildProcessResult]) -> list[JsonObject]:
    payloads: list[JsonObject] = []
    for result in child_results:
        if result.returncode != 0 or result.report_path is None:
            continue
        payloads.append(load_json_object(Path(result.report_path)))
    return payloads


def load_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        msg = f"{path} must contain a JSON object"
        raise TypeError(msg)
    return cast("JsonObject", value)


def build_metadata(
    *,
    args: BenchmarkArgs,
    timestamp: str,
    child_results: list[ChildProcessResult],
    child_payloads: list[JsonObject],
    skipped: dict[str, str],
) -> JsonObject:
    first_metadata = first_child_metadata(child_payloads)
    server = first_metadata.get("server", "isolated child benchmark processes")
    versions = first_metadata.get("package_versions")
    if not isinstance(versions, dict):
        versions = package_versions(
            ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
        )
    return {
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
            "child_count": len(child_results),
            "children": [child_result_payload(result) for result in child_results],
        },
    }


def isolation_unit(args: BenchmarkArgs) -> str:
    if args.isolation == PER_CLIENT_SCENARIO_ISOLATION:
        return "client-scenario"
    return "client"


def first_child_metadata(child_payloads: list[JsonObject]) -> JsonObject:
    if not child_payloads:
        return {}
    metadata = child_payloads[0].get("metadata")
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


def normalize_aggregate_rows(suite: str, rows: list[JsonObject]) -> list[JsonObject]:
    if suite != PROXY_CONNECT_SUITE:
        return rows
    return proxy_connect_rows_with_direct_ratios(rows)


def proxy_connect_rows_with_direct_ratios(rows: list[JsonObject]) -> list[JsonObject]:
    baselines: dict[tuple[str, str, str, int], float] = {}
    for row in rows:
        value = row.get("ok_req_s_median")
        if (
            row.get("config") == "direct"
            and row.get("lifecycle") == "reused-client"
            and isinstance(
                value,
                int | float,
            )
        ):
            baselines[proxy_connect_baseline_key(row)] = float(value)
    normalized: list[JsonObject] = []
    for row in rows:
        normalized_row = dict(row)
        value = normalized_row.get("ok_req_s_median")
        if isinstance(value, int | float):
            normalized_row["direct_ratio"] = direct_ratio(
                float(value),
                baselines.get(proxy_connect_baseline_key(normalized_row)),
            )
        normalized.append(normalized_row)
    return normalized


def proxy_connect_baseline_key(row: JsonObject) -> tuple[str, str, str, int]:
    return (
        str(row.get("mode", "")),
        str(row.get("client", "")),
        str(row.get("target_scheme", "")),
        int_value(row.get("concurrency")),
    )


def direct_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


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


def child_result_payload(result: ChildProcessResult) -> JsonObject:
    payload = asdict(result)
    return cast("JsonObject", payload)


def render_isolation_markdown(
    timestamp: str,
    args: BenchmarkArgs,
    child_results: list[ChildProcessResult],
    payload: dict[str, object],
) -> str:
    aggregate = payload.get("aggregate", [])
    runs = payload.get("runs", [])
    aggregate_count = len(aggregate) if isinstance(aggregate, list) else 0
    run_count = len(runs) if isinstance(runs, list) else 0
    template = report_environment().get_template("isolation_report.md.j2")
    return template.render(
        aggregate_count=aggregate_count,
        args=args,
        child_rows=[child_result_markdown_row(result) for result in child_results],
        run_count=run_count,
        timestamp=timestamp,
        unit=isolation_unit(args),
    )


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
        return "-"
    return f"{value:.1f}"


def optional_int(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)
