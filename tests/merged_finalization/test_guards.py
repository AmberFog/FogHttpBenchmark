from dataclasses import replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation.reports import ReportFinalizationError, write_isolation_report
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_finalization import MergedSuiteReport
from tests.isolation.args_factory import benchmark_args
from tests.isolation.report_validation_support import request_child
from tests.isolation.test_reports import proxy_row
from tests.merged_finalization.support import child_payload, proxy_children


@pytest.mark.parametrize("operation", ["filter", "reorder", "change-identity", "duplicate"])
def test_finalizer_cannot_change_aggregate_population(tmp_path: Path, operation: str) -> None:
    children = [
        request_child(tmp_path / "first", sequence=1, client="foghttp"),
        request_child(tmp_path / "second", sequence=2, client="httpx"),
    ]
    sources = {Path(child.report_path or ""): Path(child.report_path or "").read_bytes() for child in children}
    parent = tmp_path / "parent"

    def changed(rows: list[JsonObject], _children: list[JsonObject]) -> MergedSuiteReport:
        if operation == "filter":
            rows.pop()
        elif operation == "reorder":
            rows.reverse()
        elif operation == "change-identity":
            rows[0]["client"] = "different-client"
        else:
            rows.append(dict(rows[0]))
        return MergedSuiteReport(rows, {})

    error = (
        "Duplicate aggregate identity" if operation == "duplicate" else "must preserve aggregate identities and order"
    )
    with pytest.raises(ValueError, match=error):
        write_isolation_report(benchmark_args(parent), children, {}, child_cooldown_s=0.0, finalizer=changed)

    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))
    assert all(path.read_bytes() == source for path, source in sources.items())


@pytest.mark.parametrize(
    "key",
    [
        "timestamp",
        "python",
        "platform",
        "server",
        "suite",
        "args",
        "package_versions",
        "skipped",
        "isolation",
        "validity",
        "report_schema_version",
        "research_provenance",
        "package_sources",
        "timing_scope",
        "resource_metric_schema_version",
        "run_settling",
    ],
)
def test_finalizer_cannot_inject_or_replace_common_metadata(tmp_path: Path, key: str) -> None:
    child = request_child(tmp_path / "child", sequence=1, client="foghttp")
    parent = tmp_path / "parent"

    def changed(rows: list[JsonObject], _children: list[JsonObject]) -> MergedSuiteReport:
        return MergedSuiteReport(rows, {key: None})

    with pytest.raises(ReportFinalizationError, match=f"cannot replace common metadata: {key}"):
        write_isolation_report(benchmark_args(parent), [child], {}, child_cooldown_s=0.0, finalizer=changed)

    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))


@pytest.mark.parametrize(
    ("value", "error_type"),
    [(True, TypeError), (-1.0, ValueError), (float("nan"), ValueError), (float("inf"), ValueError)],
)
def test_finalizer_output_still_requires_strict_numeric_schema(
    tmp_path: Path,
    value: object,
    error_type: type[Exception],
) -> None:
    child = request_child(tmp_path / "child", sequence=1, client="foghttp")
    source = Path(child.report_path or "").read_bytes()
    parent = tmp_path / "parent"

    def changed(rows: list[JsonObject], _children: list[JsonObject]) -> MergedSuiteReport:
        rows[0]["ok_req_s_median"] = value
        return MergedSuiteReport(rows, {})

    with pytest.raises(error_type, match="ok_req_s_median"):
        write_isolation_report(benchmark_args(parent), [child], {}, child_cooldown_s=0.0, finalizer=changed)

    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))
    assert Path(child.report_path or "").read_bytes() == source


def test_callback_failure_preserves_previous_reports_and_child_files(tmp_path: Path) -> None:
    child = request_child(tmp_path / "child", sequence=1, client="foghttp")
    source = Path(child.report_path or "").read_bytes()
    parent = tmp_path / "parent"
    parent.mkdir()
    previous = {parent / "latest.json": b"previous JSON\n", parent / "latest.md": b"previous Markdown\n"}
    for path, content in previous.items():
        path.write_bytes(content)
    failure = RuntimeError("suite finalization failed")

    def failed(_rows: list[JsonObject], _children: list[JsonObject]) -> MergedSuiteReport:
        raise failure

    with pytest.raises(RuntimeError, match="suite finalization failed") as observed:
        write_isolation_report(benchmark_args(parent), [child], {}, child_cooldown_s=0.0, finalizer=failed)

    assert observed.value is failure
    assert set(parent.iterdir()) == set(previous)
    assert all(path.read_bytes() == content for path, content in previous.items())
    assert Path(child.report_path or "").read_bytes() == source


@pytest.mark.parametrize("reverse", [False, True])
def test_parent_rejects_cross_child_ambiguous_direct_baselines(tmp_path: Path, *, reverse: bool) -> None:
    baseline = proxy_row("direct-https", "direct", "reused-client", ok_req_s=100.0, direct_ratio=1.0)
    rows = [baseline, {**baseline, "request_limit": 20}]
    if reverse:
        rows.reverse()
    children = proxy_children(tmp_path, rows)
    parent = tmp_path / "parent"
    args = replace(benchmark_args(parent), suite="proxy-connect")

    with pytest.raises(ValueError, match="Ambiguous direct baseline"):
        write_isolation_report(
            args,
            children,
            {},
            child_cooldown_s=0.0,
            finalizer=get_suite(args.suite).finalize_report,
        )

    assert not list(parent.glob("*.json"))
    assert not list(parent.glob("*.md"))
    assert [child_payload(child)["aggregate"] for child in children] == [[row] for row in rows]


def test_parent_keeps_null_ratio_without_a_direct_baseline(tmp_path: Path) -> None:
    proxy = proxy_row("proxy-connect", "explicit", "cold-client", ok_req_s=50.0, direct_ratio=99.0)
    children = proxy_children(tmp_path, [proxy])
    parent = tmp_path / "parent"
    args = replace(benchmark_args(parent), suite="proxy-connect")

    write_isolation_report(args, children, {}, child_cooldown_s=0.0, finalizer=get_suite(args.suite).finalize_report)

    payload = json.loads((parent / "latest.json").read_text())
    assert payload["aggregate"][0]["direct_ratio"] is None
    assert child_payload(children[0])["aggregate"] == [proxy]
