import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from foghttp_benchmark.application import composition, execution
from foghttp_benchmark.isolation.models import CHILD_PROCESS_ISOLATION
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.validity import reports as validity_reports


@pytest.mark.parametrize("entrypoint", ["parent", "child"])
def test_research_preflight_runs_before_any_benchmark_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    checks: list[bool] = []
    work: list[BenchmarkArgs] = []

    def failed_preflight(*, check_remote: bool = False) -> JsonObject | None:
        checks.append(check_remote)
        message = "Research manifest installation does not match the release wheel"
        raise ValueError(message)

    async def unexpected_work(args: BenchmarkArgs, **_kwargs: object) -> None:
        work.append(args)

    monkeypatch.setattr(execution, "research_provenance_from_env", failed_preflight)
    monkeypatch.setattr(execution, "run_isolated_benchmark", unexpected_work)
    monkeypatch.setattr(composition, "run_benchmark_suite", unexpected_work)
    run = execution.run_benchmark if entrypoint == "parent" else execution.run_benchmark_child

    with pytest.raises(ValueError, match="does not match the release wheel"):
        asyncio.run(run(benchmark_args(tmp_path), show_progress=False))

    assert checks == [entrypoint == "parent"]
    assert work == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entrypoint", ["parent", "child"])
def test_verified_preflight_continues_into_existing_run_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    checks: list[bool] = []
    work: list[BenchmarkArgs] = []

    def verified_preflight(*, check_remote: bool = False) -> JsonObject | None:
        checks.append(check_remote)
        return {"manifest_sha256": "verified"}

    async def fake_work(args: BenchmarkArgs, **_kwargs: object) -> None:
        work.append(args)

    monkeypatch.setattr(execution, "research_provenance_from_env", verified_preflight)
    monkeypatch.setattr(execution, "run_isolated_benchmark", fake_work)
    monkeypatch.setattr(composition, "run_benchmark_suite", fake_work)
    args = benchmark_args(tmp_path)
    run = execution.run_benchmark if entrypoint == "parent" else execution.run_benchmark_child

    asyncio.run(run(args, show_progress=False))

    assert checks == [entrypoint == "parent"]
    expected_args = args if entrypoint == "parent" else replace(args, isolation=CHILD_PROCESS_ISOLATION)
    assert work == [expected_args]


def test_common_writer_includes_verified_research_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    provenance = {
        "manifest_sha256": "manifest-checksum",
        "manifest": {"foghttp_sha": "source-sha", "wheel_sha256": "wheel-checksum"},
        "installation": {"native_sha256": "native-checksum"},
    }
    sources = {"foghttp": {"source_type": "installed", "module_file": "/isolated/foghttp/__init__.py"}}
    monkeypatch.setattr(validity_reports, "research_provenance_from_env", lambda: provenance)
    monkeypatch.setattr(validity_reports, "package_sources", lambda _names: sources)
    original: JsonObject = {"suite": "requests", "package_sources": {"foghttp": {"stale": True}}}

    metadata = validity_reports.metadata_with_validity(original, [])

    assert metadata["research_provenance"] == provenance
    assert metadata["package_sources"] == sources
    assert "research_provenance" not in original
    assert original["package_sources"] == {"foghttp": {"stale": True}}


def test_common_writer_rechecks_installation_after_work(monkeypatch: pytest.MonkeyPatch) -> None:
    def changed_installation() -> JsonObject | None:
        message = "Installed native module changed after the preflight"
        raise ValueError(message)

    monkeypatch.setattr(validity_reports, "research_provenance_from_env", changed_installation)

    with pytest.raises(ValueError, match="changed after the preflight"):
        validity_reports.metadata_with_validity({"suite": "requests"}, [])


def test_common_writer_keeps_default_installation_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validity_reports, "research_provenance_from_env", lambda: None)

    metadata = validity_reports.metadata_with_validity({"suite": "requests"}, [])

    assert "research_provenance" not in metadata
    assert "package_sources" not in metadata
    assert metadata["validity"] == {
        "status": "valid",
        "is_valid": True,
        "can_compare": True,
        "reason_count": 0,
        "reason_counts": {},
        "reasons": [],
    }


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite="requests",
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=1,
        warmup=0,
        repeats=1,
        max_redirects=20,
        seed=0,
        no_shuffle=True,
        output_dir=str(output_dir),
        scenarios="json-small",
        iterations=1,
        client_counts="1",
    )
