from copy import deepcopy
import importlib.metadata
import json
from pathlib import Path
import platform
import time
from unittest.mock import Mock

import pytest

from foghttp_benchmark import attribution_evidence, provenance, reports, resources
from foghttp_benchmark.report_publication import publish_report
from foghttp_benchmark.validity import (
    classification,
    reports as validity_reports,
)


def test_publication_creates_parent_directories_and_preserves_json_and_markdown(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing" / "nested"
    payload: dict[str, object] = {"z": [None, True], "a": {"z": "世界", "a": "строка"}}
    original_payload = deepcopy(payload)
    markdown = "# Отчёт 🙂\r\nfirst|second\nlast\rline\n\n"
    expected_json = (
        '{\n  "a": {\n    "a": "\\u0441\\u0442\\u0440\\u043e\\u043a\\u0430",\n'
        '    "z": "\\u4e16\\u754c"\n  },\n  "z": [\n    null,\n    true\n  ]\n}\n'
    )

    result = publish_report(output_dir, "prepared-identifier", payload, markdown)

    assert result is None
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "latest.json",
        "latest.md",
        "prepared-identifier.json",
        "prepared-identifier.md",
    ]
    for name in ("prepared-identifier.json", "latest.json"):
        assert (output_dir / name).read_bytes() == expected_json.encode("ascii")
        assert json.loads((output_dir / name).read_text()) == payload
    for name in ("prepared-identifier.md", "latest.md"):
        assert (output_dir / name).read_bytes() == markdown.encode()
    assert payload == original_payload


def test_publication_overwrites_latest_and_retains_previous_report(tmp_path: Path) -> None:
    publish_report(tmp_path, "first", {"value": 1}, "first markdown\n")
    first_json = (tmp_path / "first.json").read_bytes()
    first_markdown = (tmp_path / "first.md").read_bytes()

    publish_report(tmp_path, "second", {"value": 2}, "second markdown")

    assert (tmp_path / "first.json").read_bytes() == first_json
    assert (tmp_path / "first.md").read_bytes() == first_markdown
    assert (tmp_path / "latest.json").read_bytes() == (tmp_path / "second.json").read_bytes()
    assert (tmp_path / "latest.md").read_text() == "second markdown"
    assert (tmp_path / "second.md").read_text() == "second markdown"


def test_publication_reuses_supplied_identifier_when_replacing_a_report(tmp_path: Path) -> None:
    publish_report(tmp_path, "20200102-030405", {"value": "before"}, "before")

    publish_report(tmp_path, "20200102-030405", {"value": "after"}, "after")

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "20200102-030405.json",
        "20200102-030405.md",
        "latest.json",
        "latest.md",
    ]
    assert json.loads((tmp_path / "20200102-030405.json").read_text()) == {"value": "after"}
    assert (tmp_path / "20200102-030405.md").read_text() == "after"


def test_publication_does_not_inspect_prepared_report_or_collect_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, object] = {"custom": {"nullable": None}, "runs": []}
    forbidden = Mock(side_effect=AssertionError("Publication crossed the prepared report boundary"))

    with monkeypatch.context() as patches:
        patches.setattr(platform, "platform", forbidden)
        patches.setattr(platform, "python_version", forbidden)
        patches.setattr(importlib.metadata, "version", forbidden)
        patches.setattr(validity_reports, "metadata_with_validity", forbidden)
        patches.setattr(classification, "classify_report_validity", forbidden)
        patches.setattr(validity_reports, "classify_report_validity", forbidden)
        patches.setattr(provenance, "capture_harness", forbidden)
        patches.setattr(provenance, "package_sources", forbidden)
        patches.setattr(provenance, "verify_research_manifest", forbidden)
        patches.setattr(attribution_evidence, "inspect_raw_evidence", forbidden)
        patches.setattr(reports, "package_versions", forbidden)
        patches.setattr(resources, "take_resource_snapshot", forbidden)
        for attribute in ("time", "perf_counter", "process_time", "strftime"):
            patches.setattr(time, attribute, forbidden)

        publish_report(tmp_path, "already-prepared", payload, "prepared markdown\n")

    assert json.loads((tmp_path / "already-prepared.json").read_text()) == payload
    assert (tmp_path / "latest.md").read_text() == "prepared markdown\n"
    forbidden.assert_not_called()
