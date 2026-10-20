__all__ = (
    "IsolationRenderContext",
    "ProfileRenderContext",
    "ProxyRenderContext",
    "RenderEnvironment",
    "SuiteRenderContext",
    "load_report_template",
    "markdown_table_cell",
    "render_compare_markdown",
    "render_isolation_markdown",
    "render_profile_markdown",
    "render_proxy_markdown",
    "render_suite_markdown",
    "report_environment",
    "resource_value",
)

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

from jinja2 import DictLoader, Environment, FileSystemLoader, Template


if TYPE_CHECKING:
    from foghttp_benchmark.compare.models import ComparisonResult
    from foghttp_benchmark.models import BenchmarkArgs, JsonObject


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
Row = TypeVar("Row")


@dataclass(frozen=True, slots=True)
class RenderEnvironment:
    python_version: str
    platform_name: str


@dataclass(frozen=True, slots=True)
class SuiteRenderContext(Generic[Row]):
    timestamp: str
    args: "BenchmarkArgs"
    aggregate: list[Row]
    skipped: dict[str, str]
    validity: object
    environment: RenderEnvironment


@dataclass(frozen=True, slots=True)
class ProxyRenderContext(Generic[Row]):
    report: SuiteRenderContext[Row]
    proxy_url: str


@dataclass(frozen=True, slots=True)
class ProfileRenderContext:
    timestamp: str
    aggregate: list["JsonObject"]
    metadata: "JsonObject"
    runs: list["JsonObject"]


@dataclass(frozen=True, slots=True)
class IsolationRenderContext:
    timestamp: str
    args: "BenchmarkArgs"
    aggregate: list["JsonObject"]
    child_rows: list[str]
    run_count: int
    unit: str
    validity: object


def report_environment() -> Environment:
    """Configure Markdown templates; template loading is the only I/O boundary here."""
    environment = Environment(
        autoescape=False,  # noqa: S701 - this template renders Markdown, not HTML.
        keep_trailing_newline=True,
        loader=FileSystemLoader(TEMPLATE_DIR),
        lstrip_blocks=True,
        trim_blocks=True,
    )
    environment.filters["markdown_table_cell"] = markdown_table_cell
    environment.filters["resource_value"] = resource_value
    return environment


def load_report_template(name: str) -> Template:
    """Load a report and its static includes before pure rendering."""
    loader = FileSystemLoader(TEMPLATE_DIR)
    environment = report_environment()
    # Imports/includes resolve lazily in Jinja. An in-memory loader keeps even
    # their first render independent of filesystem state after preparation.
    environment.loader = DictLoader(
        {template_name: loader.get_source(environment, template_name)[0] for template_name in loader.list_templates()},
    )
    return environment.get_template(name)


def render_suite_markdown(template: Template, context: SuiteRenderContext[Row]) -> str:
    return template.render(
        aggregate=context.aggregate,
        args=context.args,
        platform_name=context.environment.platform_name,
        python_version=context.environment.python_version,
        skipped=context.skipped,
        timestamp=context.timestamp,
        validity=context.validity,
    )


def render_proxy_markdown(template: Template, context: ProxyRenderContext[Row]) -> str:
    report = context.report
    return template.render(
        aggregate=report.aggregate,
        args=report.args,
        platform_name=report.environment.platform_name,
        proxy_url=context.proxy_url,
        python_version=report.environment.python_version,
        skipped=report.skipped,
        timestamp=report.timestamp,
        validity=report.validity,
    )


def render_profile_markdown(template: Template, context: ProfileRenderContext) -> str:
    return template.render(
        timestamp=context.timestamp,
        aggregate=context.aggregate,
        metadata=context.metadata,
        runs=context.runs,
    )


def render_isolation_markdown(template: Template, context: IsolationRenderContext) -> str:
    return template.render(
        aggregate=context.aggregate,
        aggregate_count=len(context.aggregate),
        args=context.args,
        child_rows=context.child_rows,
        run_count=context.run_count,
        timestamp=context.timestamp,
        unit=context.unit,
        validity=context.validity,
    )


def render_compare_markdown(template: Template, comparison: "ComparisonResult") -> str:
    return template.render(comparison=comparison)


def resource_value(value: float | None, precision: int = 0) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, int) and precision == 0:
        return str(value)
    return f"{value:.{precision}f}"


def markdown_table_cell(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", r"\|").replace("\n", "<br>")
