__all__ = ("RequestAggregateRow", "aggregate_results", "write_reports")

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from importlib import import_module, metadata
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import tomllib
from types import ModuleType

from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs, RunResult
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.resource_metrics import (
    RESOURCE_METRIC_SCHEMA_VERSION,
    ResourceCoverage,
    optional_resource_max,
    resource_coverage,
)
from foghttp_benchmark.run_settling import RunSettlingConfig, run_settling_config
from foghttp_benchmark.statistics import coefficient_of_variation, merge_error_types
from foghttp_benchmark.validity.reports import metadata_with_validity


REPORT_PACKAGES = (
    "foghttp",
    "httpx",
    "httpxyz",
    "aiohttp",
    "zapros",
    "pyreqwest",
    "faker",
    "jinja2",
    "psutil",
    "rich",
    "typer",
)


@dataclass(frozen=True, slots=True)
class RequestAggregateRow:
    mode: str
    client: str
    scenario: str
    concurrency: int
    request_limit: int
    requests: int
    repeats: int
    req_s_median: float
    ok_req_s_median: float
    req_s_cv_percent: float
    p50_ms_median: float
    p95_ms_median: float
    p99_ms_median: float
    rss_mb_max: float | None
    threads_max: int | None
    fds_max: int | None
    errors_total: int
    warmup_errors_total: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    error_rate_percent: float
    resource_coverage: ResourceCoverage = field(default_factory=dict)


def aggregate_results(results: list[RunResult]) -> list[RequestAggregateRow]:
    grouped: dict[tuple[str, str, str, int, int], list[RunResult]] = {}
    for result in results:
        key = (result.mode, result.client, result.scenario, result.concurrency, result.request_limit)
        grouped.setdefault(key, []).append(result)

    rows: list[RequestAggregateRow] = []
    for (mode, client, scenario, concurrency, request_limit), items in sorted(grouped.items()):
        requests_total = sum(item.requests for item in items)
        errors_total = sum(item.errors for item in items)
        rows.append(
            RequestAggregateRow(
                mode=mode,
                client=client,
                scenario=scenario,
                concurrency=concurrency,
                request_limit=request_limit,
                requests=items[0].requests,
                repeats=len(items),
                req_s_median=statistics.median(item.requests_per_second for item in items),
                ok_req_s_median=statistics.median(item.ok_requests_per_second for item in items),
                req_s_cv_percent=coefficient_of_variation(
                    [item.requests_per_second for item in items],
                ),
                p50_ms_median=statistics.median(item.p50_ms for item in items),
                p95_ms_median=statistics.median(item.p95_ms for item in items),
                p99_ms_median=statistics.median(item.p99_ms for item in items),
                rss_mb_max=optional_resource_max(item.peak_rss_mb for item in items),
                threads_max=optional_resource_max(item.peak_threads for item in items),
                fds_max=optional_resource_max(item.peak_fds for item in items),
                errors_total=errors_total,
                warmup_errors_total=sum(item.warmup_errors for item in items),
                error_types=merge_error_types(item.error_types for item in items),
                warmup_error_types=merge_error_types(item.warmup_error_types for item in items),
                error_rate_percent=(errors_total / requests_total) * 100 if requests_total else 0.0,
                resource_coverage=resource_coverage(
                    {
                        "rss_mb_max": [item.peak_rss_mb for item in items],
                        "threads_max": [item.peak_threads for item in items],
                        "fds_max": [item.peak_fds for item in items],
                    },
                ),
            ),
        )
    return rows


def write_reports(
    results: list[RunResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
    *,
    settling_config: RunSettlingConfig | None = None,
) -> None:
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    actual_settling_config = settling_config or run_settling_config(os.environ)
    aggregate = aggregate_results(results)
    aggregate_rows = [asdict(row) for row in aggregate]
    run_rows = [asdict(result) for result in results]
    metadata_payload = metadata_with_validity(
        {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": args.suite,
            "timing_scope": current_timing_scope(args.suite),
            "resource_metric_schema_version": RESOURCE_METRIC_SCHEMA_VERSION,
            "args": vars(args),
            "package_versions": package_versions(),
            "run_settling": {
                "cooldown_s": actual_settling_config.cooldown_s,
                "opened_connection_threshold": actual_settling_config.opened_connection_threshold,
            },
            "skipped": skipped,
        },
        aggregate_rows,
    )
    payload: dict[str, object] = {
        "metadata": metadata_payload,
        "aggregate": aggregate_rows,
        "runs": run_rows,
    }
    markdown = render_suite_markdown(
        load_report_template("report.md.j2"),
        SuiteRenderContext(
            timestamp=timestamp,
            args=args,
            aggregate=aggregate,
            skipped=skipped,
            validity=metadata_payload["validity"],
            environment=RenderEnvironment(
                python_version=platform.python_version(),
                platform_name=platform.platform(),
            ),
        ),
    )
    publish_report(output_dir, timestamp, payload, markdown)


def package_versions(names: Iterable[str] = REPORT_PACKAGES) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        versions[name] = package_version(name)
    return versions


def package_version(name: str) -> str:
    installed_version = installed_package_version(name)
    imported_version = imported_project_version(name)
    if imported_version is None or imported_version == installed_version:
        return installed_version
    if installed_version == "not installed":
        return f"{imported_version} (imported)"
    return f"{imported_version} (imported; installed {installed_version})"


def installed_package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def imported_project_version(name: str) -> str | None:
    try:
        module = import_module(name)
    except ImportError:
        return None
    return project_version_from_module(name, module)


def project_version_from_module(name: str, module: ModuleType) -> str | None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        return None
    return project_version_from_module_file(name, module_file)


def project_version_from_module_file(name: str, module_file: str) -> str | None:
    module_path = Path(module_file).resolve()
    for parent in [module_path.parent, *module_path.parents]:
        version = project_version_from_pyproject(name, parent / "pyproject.toml")
        if version is not None:
            return version
    return None


def project_version_from_pyproject(name: str, path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        pyproject = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return None
    project_name = project.get("name")
    version = project.get("version")
    if project_name != name or not isinstance(version, str):
        return None
    return version
