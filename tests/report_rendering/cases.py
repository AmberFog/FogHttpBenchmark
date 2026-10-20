from functools import partial
import json
from pathlib import Path

from foghttp_benchmark.compare.models import (
    BenchmarkRow,
    ComparisonMetadata,
    ComparisonResult,
    ComparisonValidity,
    ErrorRow,
    ResourceCoverageComparison,
    ResourceSummary,
    RowComparison,
    SegmentSummary,
)
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.rendering import (
    IsolationRenderContext,
    ProfileRenderContext,
    ProxyRenderContext,
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_compare_markdown,
    render_isolation_markdown,
    render_profile_markdown,
    render_proxy_markdown,
    render_suite_markdown,
)
from foghttp_benchmark.resource_metrics import ResourceMetricCoverage


FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE_NAMES = (
    "report.md.j2",
    "creation_report.md.j2",
    "resource_report.md.j2",
    "one_upstream_report.md.j2",
    "request_builder_report.md.j2",
    "streaming_report.md.j2",
    "proxy_connect_report.md.j2",
    "streaming_lifecycle_report.md.j2",
    "streaming_attribution_report.md.j2",
    "isolation_report.md.j2",
    "compare_report.md.j2",
)


def fixture_context(name: str) -> dict:
    return json.loads((FIXTURES / "contexts.json").read_text())[name]


def expected_markdown(name: str) -> str:
    return json.loads((FIXTURES / "expected.json").read_text())[name]


def prepared_render(name: str, payload: dict) -> partial[str]:
    template = load_report_template(name)
    if name == "compare_report.md.j2":
        return partial(render_compare_markdown, template, comparison_result(payload["comparison"]))
    if name in ("streaming_lifecycle_report.md.j2", "streaming_attribution_report.md.j2"):
        return partial(render_profile_markdown, template, ProfileRenderContext(**payload))
    if name == "isolation_report.md.j2":
        context = IsolationRenderContext(
            timestamp=payload["timestamp"],
            args=BenchmarkArgs(**payload["args"]),
            aggregate=payload["aggregate"],
            child_rows=payload["child_rows"],
            run_count=payload["run_count"],
            unit=payload["unit"],
            validity=payload["validity"],
        )
        return partial(render_isolation_markdown, template, context)
    suite = SuiteRenderContext(
        timestamp=payload["timestamp"],
        args=BenchmarkArgs(**payload["args"]),
        aggregate=payload["aggregate"],
        skipped=payload["skipped"],
        validity=payload["validity"],
        environment=RenderEnvironment(
            python_version=payload["python_version"],
            platform_name=payload["platform_name"],
        ),
    )
    if name == "proxy_connect_report.md.j2":
        return partial(render_proxy_markdown, template, ProxyRenderContext(suite, payload["proxy_url"]))
    return partial(render_suite_markdown, template, suite)


def comparison_result(payload: dict) -> ComparisonResult:
    return ComparisonResult(
        metadata=ComparisonMetadata(**payload["metadata"]),
        validity=ComparisonValidity(**payload["validity"]),
        overall=SegmentSummary(**payload["overall"]),
        by_mode=[SegmentSummary(**row) for row in payload["by_mode"]],
        by_scenario=[SegmentSummary(**row) for row in payload["by_scenario"]],
        wins=None,
        top_improvements=[row_comparison(row) for row in payload["top_improvements"]],
        top_regressions=[row_comparison(row) for row in payload["top_regressions"]],
        new_error_rows=[
            ErrorRow(mode="async", client="foghttp", scenario="small", **row) for row in payload["new_error_rows"]
        ],
        resource_summary=ResourceSummary(**payload["resource_summary"]),
        resource_coverage=tuple(
            ResourceCoverageComparison(
                **{
                    **row,
                    "old": {key: ResourceMetricCoverage(**value) for key, value in row["old"].items()},
                    "new": {key: ResourceMetricCoverage(**value) for key, value in row["new"].items()},
                },
            )
            for row in payload["resource_coverage"]
        ),
        unmatched_old_rows=payload["unmatched_old_rows"],
        unmatched_new_rows=payload["unmatched_new_rows"],
    )


def row_comparison(payload: dict) -> RowComparison:
    row = BenchmarkRow(
        suite="requests",
        identity=(payload["row"]["label"],),
        group=(),
        label=payload["row"]["label"],
        mode="async",
        client="foghttp",
        scenario="small",
        primary_value=payload["new_primary"],
        p95_ms=payload["new_p95_ms"],
        p99_ms=None,
        errors_total=payload["new_errors_total"],
        warmup_errors_total=0,
        error_rate_percent=None,
        rss_mb=None,
        threads=0,
        fds=0,
    )
    return RowComparison(
        **{**payload, "row": row},
        old_p99_ms=None,
        new_p99_ms=None,
        p99_ratio=None,
        old_error_rate_percent=None,
        new_error_rate_percent=None,
    )
