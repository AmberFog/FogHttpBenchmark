__all__ = ("RequestAggregateRow", "aggregate_results", "write_reports")

from dataclasses import asdict, dataclass
from importlib import import_module, metadata
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import tomllib
from types import ModuleType

from jinja2 import Environment, FileSystemLoader

from foghttp_benchmark.constants import MIN_VARIATION_SAMPLES
from foghttp_benchmark.models import BenchmarkArgs, RunResult


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


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
    rss_mb_max: float
    threads_max: int
    fds_max: int
    errors_total: int
    warmup_errors_total: int
    error_rate_percent: float


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
                rss_mb_max=max((item.peak_rss_mb or 0.0) for item in items),
                threads_max=max((item.peak_threads or 0) for item in items),
                fds_max=max((item.peak_fds or 0) for item in items),
                errors_total=errors_total,
                warmup_errors_total=sum(item.warmup_errors for item in items),
                error_rate_percent=(errors_total / requests_total) * 100 if requests_total else 0.0,
            ),
        )
    return rows


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def write_reports(results: list[RunResult], skipped: dict[str, str], args: BenchmarkArgs) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": args.suite,
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "httpxyz", "aiohttp", "zapros", "faker", "jinja2", "psutil", "rich", "typer"],
            ),
            "skipped": skipped,
        },
        "aggregate": [asdict(row) for row in aggregate],
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_markdown_report(timestamp, aggregate, skipped, args)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_markdown_report(
    timestamp: str,
    aggregate: list[RequestAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )


def report_environment() -> Environment:
    return Environment(
        autoescape=False,  # noqa: S701 - this template renders Markdown, not HTML.
        keep_trailing_newline=True,
        loader=FileSystemLoader(TEMPLATE_DIR),
        lstrip_blocks=True,
        trim_blocks=True,
    )


def package_versions(names: list[str]) -> dict[str, str]:
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
