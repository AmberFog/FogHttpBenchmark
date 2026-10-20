from dataclasses import asdict, replace
from importlib import import_module
import json
from pathlib import Path

import pytest

from foghttp_benchmark.compare.loading import load_benchmark_report
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.validity.classification import classify_report_validity
from foghttp_benchmark.validity.serialization import validity_payload
from tests.publication_consumers.support import (
    REPORT_NAMES,
    REPORT_TIMESTAMP,
    existing_outputs,
    output_contents,
)
from tests.resource.factories import benchmark_args
from tests.resource_metrics.cases import ResourceReportCase


def test_suite_publishes_complete_prepared_report(tmp_path: Path, report_case: ResourceReportCase) -> None:
    output_dir = tmp_path / "nested" / "report"
    args = replace(benchmark_args(output_dir), suite=report_case.suite)

    report_case.writer(args)

    contents = output_contents(output_dir)
    assert set(contents) == set(REPORT_NAMES)
    assert contents[f"{REPORT_TIMESTAMP}.json"] == contents["latest.json"]
    assert contents[f"{REPORT_TIMESTAMP}.md"] == contents["latest.md"]
    payload = json.loads(contents["latest.json"])
    assert contents["latest.json"] == (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    assert contents["latest.md"]
    metadata = payload["metadata"]
    assert metadata["timestamp"] == REPORT_TIMESTAMP
    assert metadata["suite"] == report_case.suite
    assert metadata["timing_scope"] == current_timing_scope(report_case.suite)
    assert metadata["args"] == vars(args)
    assert metadata["package_versions"] == {"foghttp": "0.4.2-fixture"}
    assert payload["aggregate"]
    assert payload["runs"] == [asdict(result) for result in report_case.writer.args[0]]
    assert metadata["validity"] == validity_payload(
        classify_report_validity(suite=report_case.suite, aggregate_rows=payload["aggregate"], metadata=metadata),
    )
    loaded = load_benchmark_report(output_dir / "latest.json")
    assert loaded.suite == report_case.suite
    assert loaded.aggregate_rows == payload["aggregate"]
    assert f"- Status: `{metadata['validity']['status']}`" in (output_dir / "latest.md").read_text()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("stage", ["metadata", "render"])
def test_suite_preparation_failure_preserves_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_case: ResourceReportCase,
    stage: str,
    *,
    existing: bool,
) -> None:
    output_dir = tmp_path / "nested" / "report"
    previous = existing_outputs(output_dir, existing=existing)
    args = replace(benchmark_args(output_dir), suite=report_case.suite)
    module = import_module(report_case.writer.func.__module__)
    renderer_name = "render_proxy_markdown" if report_case.suite == "proxy-connect" else "render_suite_markdown"
    target = "metadata_with_validity" if stage == "metadata" else renderer_name

    def reject_preparation(*_args: object, **_kwargs: object) -> None:
        msg = "report preparation blocked"
        raise RuntimeError(msg)

    monkeypatch.setattr(module, target, reject_preparation)

    with pytest.raises(RuntimeError, match="report preparation blocked"):
        report_case.writer(args)

    assert output_contents(output_dir) == previous
    assert output_dir.exists() is existing
    if not existing:
        assert not output_dir.parent.exists()


def test_suite_prepares_markdown_before_rejecting_file_as_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_case: ResourceReportCase,
) -> None:
    output_dir = tmp_path / "report"
    output_dir.write_bytes(b"existing file\n")
    args = replace(benchmark_args(output_dir), suite=report_case.suite)
    module = import_module(report_case.writer.func.__module__)
    renderer_name = "render_proxy_markdown" if report_case.suite == "proxy-connect" else "render_suite_markdown"
    original_renderer = getattr(module, renderer_name)
    rendered = []

    def record_render(*args: object, **kwargs: object) -> str:
        markdown = original_renderer(*args, **kwargs)
        rendered.append(markdown)
        return markdown

    monkeypatch.setattr(module, renderer_name, record_render)

    with pytest.raises(FileExistsError):
        report_case.writer(args)

    assert len(rendered) == 1
    assert rendered[0]
    assert output_dir.read_bytes() == b"existing file\n"
    assert list(tmp_path.iterdir()) == [output_dir]
