__all__ = ("write_resource_reports",)

from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys
import time

from foghttp_benchmark.models import BenchmarkArgs, ResourceBackpressureResult
from foghttp_benchmark.reports import package_versions, report_environment
from foghttp_benchmark.resource.reporting.aggregation import aggregate_resource_results
from foghttp_benchmark.resource.reporting.models import ResourceAggregateRow


def write_resource_reports(
    results: list[ResourceBackpressureResult],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_resource_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "suite": args.suite,
            "args": vars(args),
            "resource_cases": sorted({result.scenario for result in results}),
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

    markdown = render_resource_markdown_report(timestamp, aggregate, skipped, args)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_resource_markdown_report(
    timestamp: str,
    aggregate: list[ResourceAggregateRow],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("resource_report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )
