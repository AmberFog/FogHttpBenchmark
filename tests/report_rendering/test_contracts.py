from copy import deepcopy
import importlib.metadata
from pathlib import Path
import platform
import time
from unittest.mock import Mock

from jinja2 import FileSystemLoader
import pytest

from foghttp_benchmark import attribution_evidence, provenance, reports, resources
from foghttp_benchmark.rendering import markdown_table_cell, report_environment
from foghttp_benchmark.validity import (
    classification,
    reports as validity_reports,
)
from tests.report_rendering.cases import TEMPLATE_NAMES, expected_markdown, fixture_context, prepared_render


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_rendering_preserves_captured_report_bytes_without_mutating_context(name: str) -> None:
    payload = fixture_context(name)
    before = deepcopy(payload)
    render = prepared_render(name, payload)
    context_before = deepcopy(render.args[1])

    assert render() == expected_markdown(name)
    assert render() == expected_markdown(name)
    assert payload == before
    assert render.args[1] == context_before


def test_request_report_preserves_supplied_skipped_client_order() -> None:
    payload = fixture_context("report.md.j2")
    payload["skipped"] = {
        "z-last": "first supplied client",
        "a-first": "second supplied client",
    }

    markdown = prepared_render("report.md.j2", payload)()

    assert markdown.index("- `z-last`: first supplied client") < markdown.index("- `a-first`: second supplied client")


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_ready_context_renders_without_environment_validity_clock_or_file_work(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = expected_markdown(name)
    render = prepared_render(name, fixture_context(name))
    forbidden = Mock(side_effect=AssertionError("Rendering crossed the prepared context boundary"))

    with monkeypatch.context() as patches:
        patches.setattr("builtins.open", forbidden)
        for attribute in ("open", "read_text", "read_bytes", "write_text", "write_bytes"):
            patches.setattr(Path, attribute, forbidden)
        patches.setattr(FileSystemLoader, "get_source", forbidden)
        patches.setattr(platform, "platform", forbidden)
        patches.setattr(platform, "python_version", forbidden)
        patches.setattr(importlib.metadata, "version", forbidden)
        patches.setattr(validity_reports, "metadata_with_validity", forbidden)
        patches.setattr(classification, "classify_report_validity", forbidden)
        patches.setattr(validity_reports, "classify_report_validity", forbidden)
        patches.setattr(provenance, "capture_harness", forbidden)
        patches.setattr(provenance, "package_sources", forbidden)
        patches.setattr(attribution_evidence, "inspect_raw_evidence", forbidden)
        patches.setattr(reports, "package_versions", forbidden)
        patches.setattr(reports, "imported_project_version", forbidden)
        patches.setattr(resources, "take_resource_snapshot", forbidden)
        for attribute in ("time", "perf_counter", "process_time"):
            patches.setattr(time, attribute, forbidden)

        actual = render()
        repeated = render()

    assert actual == expected
    assert repeated == expected
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a|b\r\nc\rd\ne", r"a\|b<br>c<br>d<br>e"),
        ("строка|🙂\n世界", r"строка\|🙂<br>世界"),
        (None, "None"),
        (0, "0"),
        ("", ""),
    ],
)
def test_table_cell_filter_preserves_line_normalization_and_unicode(value: object, expected: str) -> None:
    template = report_environment().from_string("{{ value|markdown_table_cell }}")

    assert markdown_table_cell(value) == expected
    assert template.render(value=value) == expected
