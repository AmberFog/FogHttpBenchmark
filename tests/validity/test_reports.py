from foghttp_benchmark.reports import report_environment
from foghttp_benchmark.validity.models import ValidityReason, ValiditySummary
from foghttp_benchmark.validity.serialization import validity_payload


def test_validity_markdown_escapes_table_cells() -> None:
    summary = ValiditySummary(
        status="needs-rerun",
        is_valid=False,
        can_compare=False,
        reason_count=1,
        reason_counts={"needs-rerun": 1},
        reasons=(
            ValidityReason(
                status="needs-rerun",
                code="unexpected|errors",
                message="line one|line two\nline three",
                row_label="async / foghttp|httpx",
                row={},
            ),
        ),
    )

    template = report_environment().from_string(
        '{% import "validity.md.j2" as validity %}{{ validity.summary(payload) }}',
    )
    markdown = template.render(payload=validity_payload(summary))

    assert "unexpected\\|errors" in markdown
    assert "async / foghttp\\|httpx" in markdown
    assert "line one\\|line two<br>line three" in markdown
