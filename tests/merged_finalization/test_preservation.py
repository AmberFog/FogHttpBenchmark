from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_finalization import MergedSuiteReport
from tests.isolation.args_factory import benchmark_args
from tests.isolation.report_validation_support import request_child
from tests.merged_finalization.support import child_payload


@pytest.mark.parametrize("stored_verdict", [False, True])
def test_callback_mutation_cannot_erase_child_validity_provenance_or_runs(
    tmp_path: Path,
    *,
    stored_verdict: bool,
) -> None:
    child = request_child(tmp_path / "child", sequence=1, client="foghttp")
    path = Path(child.report_path or "")
    payload = json.loads(path.read_text())
    provenance = {"manifest_sha256": "saved-proof", "manifest": {"wheel_sha256": "saved-wheel"}}
    package_sources = {"foghttp": {"module_file": "/isolated/foghttp/__init__.py"}}
    payload["metadata"].update(research_provenance=provenance, package_sources=package_sources)
    if stored_verdict:
        payload["metadata"]["validity"] = {
            "status": "invalid",
            "can_compare": False,
            "reasons": [{"status": "invalid", "code": "prior_host_failure"}],
        }
    else:
        payload["metadata"].pop("validity", None)
        payload["aggregate"][0].update(errors_total=1, error_types={"RuntimeError": 1})
    path.write_text(json.dumps(payload))
    source = path.read_bytes()
    parent = tmp_path / "parent"

    def changed(rows: list[JsonObject], children: list[JsonObject]) -> MergedSuiteReport:
        metadata = children[0]
        metadata["validity"] = {"status": "valid", "can_compare": True, "reasons": []}
        metadata["research_provenance"]["manifest"].clear()
        metadata["package_sources"]["foghttp"].clear()
        metadata["args"]["scenarios"] = "changed-by-finalizer"
        metadata["isolation"] = {"children": []}
        rows[0].update(errors_total=0, error_types={})
        return MergedSuiteReport(rows, {})

    write_isolation_report(benchmark_args(parent), [child], {}, child_cooldown_s=0.0, finalizer=changed)

    merged = json.loads((parent / "latest.json").read_text())
    metadata = merged["metadata"]
    expected_status = "invalid" if stored_verdict else "needs-rerun"
    expected_code = "prior_host_failure" if stored_verdict else "unexpected_measured_errors"
    assert metadata["validity"]["status"] == expected_status
    assert metadata["validity"]["can_compare"] is False
    assert expected_code in {reason["code"] for reason in metadata["validity"]["reasons"]}
    assert metadata["research_provenance"] == provenance
    assert metadata["package_sources"] == package_sources
    diagnostic = metadata["isolation"]["children"][0]
    assert diagnostic["research_provenance"] == provenance
    assert diagnostic["package_sources"] == package_sources
    assert diagnostic["stdout_tail"] == child.stdout_tail
    assert diagnostic["stderr_tail"] == child.stderr_tail
    if stored_verdict:
        assert diagnostic["validity"] == payload["metadata"]["validity"]
    assert metadata["args"]["scenarios"] == benchmark_args(parent).scenarios
    assert merged["runs"] == payload["runs"]
    assert path.read_bytes() == source


def test_mixed_child_outcomes_keep_diagnostics_and_invalidate_parent(tmp_path: Path) -> None:
    successful = request_child(tmp_path / "successful", sequence=1, client="foghttp")
    failed = replace(
        request_child(tmp_path / "failed", sequence=2, client="httpx"),
        returncode=2,
        stderr_tail="failed-child-diagnostics",
    )
    missing = replace(
        successful,
        sequence=3,
        client="missing",
        report_path=None,
        stdout_tail="missing-output-diagnostics",
    )
    children = [successful, failed, missing]
    sources = {Path(child.report_path): Path(child.report_path).read_bytes() for child in children if child.report_path}
    parent = tmp_path / "parent"
    args = benchmark_args(parent)

    write_isolation_report(args, children, {}, child_cooldown_s=0.0, finalizer=get_suite(args.suite).finalize_report)

    payload = json.loads((parent / "latest.json").read_text())
    assert payload["aggregate"] == child_payload(successful)["aggregate"]
    assert payload["runs"] == child_payload(successful)["runs"]
    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["validity"]["can_compare"] is False
    reasons = payload["metadata"]["validity"]["reasons"]
    assert {reason["row"]["sequence"] for reason in reasons if reason["code"] == "isolated_child_failed"} == {2, 3}
    diagnostics = payload["metadata"]["isolation"]["children"]
    assert diagnostics[1] == asdict(failed)
    assert diagnostics[2] == asdict(missing)
    assert all(diagnostics[0][key] == value for key, value in asdict(successful).items())
    assert all(path.read_bytes() == source for path, source in sources.items())
