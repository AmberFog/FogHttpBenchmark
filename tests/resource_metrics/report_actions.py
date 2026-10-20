from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path

from foghttp_benchmark.models import ResourceBackpressureResult
from foghttp_benchmark.proxy_connect.models import ProxyConnectResult
from foghttp_benchmark.streaming.models import StreamingResult
from tests.resource.factories import benchmark_args
from tests.resource_metrics.cases import ResourceField, ResourceReportCase, ResourceResult


def resource_results(
    case: ResourceReportCase,
    observations: Sequence[int | float | None],
) -> list[ResourceResult]:
    original = case.writer.args[0][0]
    results = []
    for repeat, observation in enumerate(observations, start=1):
        changes: dict[str, object] = {"repeat": repeat}
        stats = (
            dict(original.client_stats or {})
            if isinstance(original, ResourceBackpressureResult | ProxyConnectResult | StreamingResult)
            else {}
        )
        for index, metric in enumerate(case.metrics, start=1):
            value = observation * index if observation is not None else None
            if metric.client_stat:
                stats.pop(metric.source, None)
                if value is not None:
                    stats[metric.source] = value
            else:
                changes[metric.source] = value
        if any(metric.client_stat for metric in case.metrics):
            changes["client_stats"] = stats or None
        results.append(replace(original, **changes))
    return results


def write_resource_case(
    case: ResourceReportCase,
    directory: Path,
    observations: Sequence[int | float | None],
) -> Path:
    write_resource_results(case, directory, resource_results(case, observations))
    return directory / "latest.json"


def write_resource_results(case: ResourceReportCase, directory: Path, results: list[ResourceResult]) -> None:
    args = replace(benchmark_args(directory), suite=case.suite)
    case.writer.func(results, *case.writer.args[1:], args, **(case.writer.keywords or {}))


def replace_resource_metric(result: ResourceResult, metric: ResourceField, value: object) -> ResourceResult:
    if metric.client_stat and isinstance(result, ResourceBackpressureResult | ProxyConnectResult | StreamingResult):
        return replace(result, client_stats={**(result.client_stats or {}), metric.source: value})
    return replace(result, **{metric.source: value})


def report_payload(path: Path) -> dict:
    return json.loads(path.read_text())


def remove_resource_coverage(path: Path) -> dict:
    payload = report_payload(path)
    payload["metadata"].pop("resource_metric_schema_version")
    for row in payload["aggregate"]:
        row.pop("resource_coverage")
    path.write_text(json.dumps(payload))
    return payload
