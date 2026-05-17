__all__ = (
    "build_comparison",
    "render_compare_markdown",
    "write_or_print_compare_report",
)

from pathlib import Path

import typer

from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.models import ComparisonResult
from foghttp_benchmark.reports import report_environment


def build_comparison(
    old_path: Path,
    new_path: Path,
    *,
    focus_client: str,
    top_n: int,
) -> ComparisonResult:
    old_report = load_benchmark_report(old_path)
    new_report = load_benchmark_report(new_path)
    return compare_reports(
        old_report,
        new_report,
        focus_client=focus_client,
        top_n=top_n,
    )


def write_or_print_compare_report(
    comparison: ComparisonResult,
    output_path: Path | None,
) -> None:
    markdown = render_compare_markdown(comparison)
    if output_path is None:
        typer.echo(markdown, nl=False)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)


def render_compare_markdown(comparison: ComparisonResult) -> str:
    template = report_environment().get_template("compare_report.md.j2")
    return template.render(comparison=comparison)
