__all__ = (
    "build_comparison",
    "write_or_print_compare_report",
)

from pathlib import Path

import typer

from foghttp_benchmark.compare.analysis import compare_reports
from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.compare.models import ComparisonResult
from foghttp_benchmark.rendering import load_report_template, render_compare_markdown


def build_comparison(
    old_path: Path,
    new_path: Path,
    *,
    focus_client: str,
    top_n: int,
    comparison_axis: str | None = None,
) -> ComparisonResult:
    old_report = load_benchmark_report(old_path)
    new_report = load_benchmark_report(new_path)
    return compare_reports(
        old_report,
        new_report,
        focus_client=focus_client,
        top_n=top_n,
        comparison_axis=comparison_axis,
    )


def write_or_print_compare_report(
    comparison: ComparisonResult,
    output_path: Path | None,
) -> None:
    markdown = render_compare_markdown(load_report_template("compare_report.md.j2"), comparison)
    if output_path is None:
        typer.echo(markdown, nl=False)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown)
