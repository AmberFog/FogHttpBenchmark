import json
from pathlib import Path

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation import reports
from foghttp_benchmark.isolation.models import ChildProcessResult
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_finalization import MergedSuiteReport
from tests.isolation.report_rows import request_aggregate, request_run
from tests.isolation.test_reports import CHILD_COOLDOWN_S, benchmark_args, child_result, write_child_report
from tests.publication_consumers.support import (
    REPORT_NAMES,
    REPORT_TIMESTAMP,
    existing_outputs,
    output_contents,
)


@pytest.fixture
def children(tmp_path: Path) -> list[ChildProcessResult]:
    report = write_child_report(
        tmp_path / "child",
        client="foghttp",
        aggregate=[request_aggregate("foghttp")],
        runs=[request_run("foghttp")],
        skipped={"async:httpx": "child skipped"},
    )
    return [child_result(1, "foghttp", report)]


def test_isolation_publishes_complete_finalized_report(tmp_path: Path, children: list[ChildProcessResult]) -> None:
    output_dir = tmp_path / "nested" / "parent"
    args = benchmark_args(output_dir)

    reports.write_isolation_report(
        args,
        children,
        {"async:aiohttp": "parent skipped"},
        child_cooldown_s=CHILD_COOLDOWN_S,
        finalizer=get_suite(args.suite).finalize_report,
    )

    contents = output_contents(output_dir)
    assert set(contents) == set(REPORT_NAMES)
    assert contents[f"{REPORT_TIMESTAMP}.json"] == contents["latest.json"]
    assert contents[f"{REPORT_TIMESTAMP}.md"] == contents["latest.md"]
    payload = json.loads(contents["latest.json"])
    assert contents["latest.json"] == (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    assert contents["latest.md"]
    metadata = payload["metadata"]
    assert metadata["timestamp"] == REPORT_TIMESTAMP
    assert metadata["suite"] == args.suite
    assert metadata["timing_scope"] == "requests-load-only-v2"
    assert metadata["skipped"] == {"async:httpx": "child skipped", "async:aiohttp": "parent skipped"}
    assert metadata["isolation"]["children"][0]["report_path"] == children[0].report_path
    assert metadata["validity"]["status"] == "valid"
    assert payload["aggregate"] == [request_aggregate("foghttp")]
    assert payload["runs"] == [request_run("foghttp")]
    assert "- Status: `valid`" in (output_dir / "latest.md").read_text()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("stage", ["finalization", "render"])
def test_isolation_preparation_failure_preserves_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    children: list[ChildProcessResult],
    stage: str,
    *,
    existing: bool,
) -> None:
    output_dir = tmp_path / "nested" / "parent"
    previous = existing_outputs(output_dir, existing=existing)
    args = benchmark_args(output_dir)
    finalizer = get_suite(args.suite).finalize_report

    def replace_identity(rows: list[JsonObject], _metadata: list[JsonObject]) -> MergedSuiteReport:
        rows[0]["client"] = "unexpected-client"
        return MergedSuiteReport(rows, {})

    def reject_render(*_args: object, **_kwargs: object) -> str:
        msg = "isolation render blocked"
        raise RuntimeError(msg)

    if stage == "finalization":
        finalizer = replace_identity
        error = reports.ReportFinalizationError
        message = "preserve aggregate identities"
    else:
        monkeypatch.setattr(reports, "render_isolation_markdown", reject_render)
        error = RuntimeError
        message = "isolation render blocked"

    with pytest.raises(error, match=message):
        reports.write_isolation_report(
            args,
            children,
            {},
            child_cooldown_s=CHILD_COOLDOWN_S,
            finalizer=finalizer,
        )

    assert output_contents(output_dir) == previous
    assert output_dir.exists() is existing
    if not existing:
        assert not output_dir.parent.exists()


def test_isolation_prepares_markdown_before_rejecting_file_as_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    children: list[ChildProcessResult],
) -> None:
    output_dir = tmp_path / "parent"
    output_dir.write_bytes(b"existing file\n")
    args = benchmark_args(output_dir)
    original_renderer = reports.render_isolation_markdown
    rendered = []

    def record_render(*args: object, **kwargs: object) -> str:
        markdown = original_renderer(*args, **kwargs)
        rendered.append(markdown)
        return markdown

    monkeypatch.setattr(reports, "render_isolation_markdown", record_render)

    with pytest.raises(FileExistsError):
        reports.write_isolation_report(
            args,
            children,
            {},
            child_cooldown_s=CHILD_COOLDOWN_S,
            finalizer=get_suite(args.suite).finalize_report,
        )

    assert len(rendered) == 1
    assert rendered[0]
    assert output_dir.read_bytes() == b"existing file\n"
