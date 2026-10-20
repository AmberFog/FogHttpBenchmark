from dataclasses import asdict, replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation.reports import write_isolation_report
from tests.isolation.args_factory import benchmark_args
from tests.report_schema.decoding_fixtures import (
    child_process_result,
    payload_rows,
    report_payload,
    write_payload,
)
from tests.report_schema.ordinary_fixtures import ORDINARY_SUITES


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_parent_rejects_colliding_children_before_normalization_or_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    first_payload = report_payload(suite)
    second_payload = report_payload(suite)
    payload_rows(first_payload)[0]["rss_mb_max"] = 10.0
    payload_rows(second_payload)[0]["rss_mb_max"] = 20.0
    first = write_payload(tmp_path / "first", first_payload)
    second = write_payload(tmp_path / "second", second_payload)
    sources = {path: path.read_bytes() for path in (first, second)}
    children = [child_process_result(first), replace(child_process_result(second), sequence=2)]
    diagnostics = [asdict(child) for child in children]
    normalizer = Mock(side_effect=AssertionError("Duplicate detection must precede normalization"))
    parent = tmp_path / "parent"

    with pytest.raises(ValueError, match="Duplicate aggregate identity") as error:
        write_isolation_report(
            replace(benchmark_args(parent), suite=suite),
            children,
            {},
            finalizer=normalizer,
            child_cooldown_s=0.0,
        )

    assert f"{first}:aggregate[0]" in str(error.value)
    assert f"{second}:aggregate[0]" in str(error.value)
    assert all(path.read_bytes() == source for path, source in sources.items())
    assert [asdict(child) for child in children] == diagnostics
    normalizer.assert_not_called()
    assert not parent.exists()


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_parent_rejects_duplicate_rows_inside_one_successful_child(
    tmp_path: Path,
    suite: str,
) -> None:
    payload = report_payload(suite)
    rows = payload_rows(payload)
    rows.append(dict(rows[0], rss_mb_max=20.0))
    path = write_payload(tmp_path / "child", payload)
    source = path.read_bytes()
    child = child_process_result(path)
    diagnostics = asdict(child)
    parent = tmp_path / "parent"

    with pytest.raises(ValueError, match="Duplicate aggregate identity") as error:
        write_isolation_report(
            replace(benchmark_args(parent), suite=suite),
            [child],
            {},
            finalizer=get_suite(suite).finalize_report,
            child_cooldown_s=0.0,
        )

    assert str(path) in str(error.value)
    assert "aggregate[0]" in str(error.value)
    assert "aggregate[1]" in str(error.value)
    assert path.read_bytes() == source
    assert asdict(child) == diagnostics
    assert not parent.exists()


@pytest.mark.parametrize("suite", ORDINARY_SUITES)
def test_parent_preserves_nonoverlapping_aggregates_and_repeated_raw_identities(
    tmp_path: Path,
    suite: str,
) -> None:
    children = []
    sources = {}
    expected_runs = []
    for sequence, client in enumerate(("foghttp", "httpx"), start=1):
        payload = report_payload(suite)
        payload_rows(payload)[0]["client"] = client
        runs = payload_rows(payload, "runs")
        runs[0]["client"] = client
        runs.append(dict(runs[0], repeat=1))
        expected_runs.extend(runs)
        path = write_payload(tmp_path / client, payload)
        sources[path] = path.read_bytes()
        children.append(replace(child_process_result(path), client=client, sequence=sequence))
    parent = tmp_path / "parent"

    write_isolation_report(
        replace(benchmark_args(parent), suite=suite),
        children,
        {},
        finalizer=get_suite(suite).finalize_report,
        child_cooldown_s=0.0,
    )

    merged = json.loads((parent / "latest.json").read_text())
    assert [row["client"] for row in merged["aggregate"]] == ["foghttp", "httpx"]
    assert [row["repeats"] for row in merged["aggregate"]] == [2, 2]
    assert merged["runs"] == expected_runs
    assert all(path.read_bytes() == source for path, source in sources.items())
    assert (parent / "latest.md").is_file()


def test_parent_keeps_failed_child_diagnostics_without_merging_its_duplicate_rows(tmp_path: Path) -> None:
    successful = write_payload(tmp_path / "successful", report_payload())
    failed_payload = report_payload()
    rows = payload_rows(failed_payload)
    rows.append(dict(rows[0]))
    failed = write_payload(tmp_path / "failed", failed_payload)
    source = failed.read_bytes()
    failed_child = replace(child_process_result(failed), sequence=2, returncode=2)
    parent = tmp_path / "parent"

    write_isolation_report(
        benchmark_args(parent),
        [child_process_result(successful), failed_child],
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=0.0,
    )

    payload = json.loads((parent / "latest.json").read_text())
    assert len(payload["aggregate"]) == 1
    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["isolation"]["children"][1] == asdict(failed_child)
    assert failed.read_bytes() == source


def test_parent_preserves_existing_reports_when_children_collide(tmp_path: Path) -> None:
    first = write_payload(tmp_path / "first", report_payload())
    second = write_payload(tmp_path / "second", report_payload())
    parent = tmp_path / "parent"
    parent.mkdir()
    existing = {
        parent / "latest.json": b"previous parent JSON\n",
        parent / "latest.md": b"previous parent Markdown\n",
    }
    for path, content in existing.items():
        path.write_bytes(content)

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        write_isolation_report(
            benchmark_args(parent),
            [child_process_result(first), replace(child_process_result(second), sequence=2)],
            {},
            finalizer=get_suite("requests").finalize_report,
            child_cooldown_s=0.0,
        )

    assert set(parent.iterdir()) == set(existing)
    assert all(path.read_bytes() == content for path, content in existing.items())
