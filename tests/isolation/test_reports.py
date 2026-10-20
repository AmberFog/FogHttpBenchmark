from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
    REQUESTS_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.measurement_timing import current_timing_scope
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.reports import write_reports
from foghttp_benchmark.validity import reports as validity_reports
from tests.isolation.report_rows import request_aggregate, request_run, streaming_aggregate, streaming_run
from tests.requests.factories import run_result


CHILD_COUNT = 2
FAILED_EXIT_CODE = 2
EXPECTED_COLD_DIRECT_RATIO = 0.5
CHILD_COOLDOWN_S = 15.0
RUN_COOLDOWN_S = 3.0
RUN_COOLDOWN_OPENED_THRESHOLD = 256
EXPECTED_MERGED_REQUEST_ERRORS = 3
EXPECTED_MERGED_WARMUP_ERRORS = 2


def test_isolation_report_merges_successful_child_reports(tmp_path: Path) -> None:
    first_aggregate = request_aggregate("foghttp")
    second_aggregate = request_aggregate("httpx", ok_req_s=90.0)
    first_run = request_run("foghttp")
    second_run = request_run("httpx", ok_req_s=90.0)
    first_report = write_child_report(
        tmp_path / "child-1",
        client="foghttp",
        aggregate=[first_aggregate],
        runs=[first_run],
        skipped={},
    )
    second_report = write_child_report(
        tmp_path / "child-2",
        client="httpx",
        aggregate=[second_aggregate],
        runs=[second_run],
        skipped={"sync:httpx": "not requested by test"},
    )
    args = benchmark_args(tmp_path / "parent")
    results = [
        child_result(1, "foghttp", first_report),
        child_result(2, "httpx", second_report),
    ]

    write_isolation_report(
        args,
        results,
        {"async:aiohttp": "unsupported in this suite"},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((tmp_path / "parent" / "latest.json").read_text())
    metadata = payload["metadata"]
    assert metadata["suite"] == REQUESTS_SUITE
    assert metadata["timing_scope"] == "requests-load-only-v2"
    assert metadata["isolation"]["backend"] == "subprocess"
    assert metadata["isolation"]["scheduler"] == "sequential"
    assert metadata["isolation"]["child_cooldown_s"] == CHILD_COOLDOWN_S
    assert metadata["run_settling"] == {
        "cooldown_s": RUN_COOLDOWN_S,
        "opened_connection_threshold": RUN_COOLDOWN_OPENED_THRESHOLD,
    }
    assert len(metadata["isolation"]["children"]) == CHILD_COUNT
    assert payload["aggregate"] == [first_aggregate, second_aggregate]
    assert payload["runs"] == [first_run, second_run]
    assert metadata["skipped"] == {
        "async:aiohttp": "unsupported in this suite",
        "sync:httpx": "not requested by test",
    }
    assert "subprocess" in (tmp_path / "parent" / "latest.md").read_text()


@pytest.mark.parametrize(
    ("suite", "scenario"),
    [(REQUESTS_SUITE, "post-echo-64k"), (COMPRESSED_RESPONSE_SUITE, "gzip-64k")],
)
def test_isolation_report_preserves_child_measured_and_warmup_error_types(
    tmp_path: Path,
    suite: str,
    scenario: str,
) -> None:
    children: list[ChildProcessResult] = []
    expected_runs: list[dict[str, object]] = []
    clients = {"foghttp": "RequestError", "httpx": "ConnectError"}
    for sequence, (client, error_type) in enumerate(clients.items(), start=1):
        output_dir = tmp_path / client
        results = [
            replace(
                run_result(
                    repeat=repeat,
                    errors=repeat + 1,
                    warmup_errors=1,
                    error_types={error_type: repeat + 1},
                    warmup_error_types={"TimeoutError": 1},
                ),
                client=client,
                scenario=scenario,
            )
            for repeat in range(2)
        ]
        write_reports(results, {}, benchmark_args(output_dir, suite=suite))
        children.append(child_result(sequence, client, output_dir / "latest.json"))
        expected_runs.extend(asdict(result) for result in results)

    parent_dir = tmp_path / "parent"
    write_isolation_report(
        benchmark_args(parent_dir, suite=suite),
        children,
        {},
        finalizer=get_suite(suite).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((parent_dir / "latest.json").read_text())
    assert payload["metadata"]["suite"] == suite
    assert len(payload["aggregate"]) == len(clients)
    for row in payload["aggregate"]:
        assert row["errors_total"] == EXPECTED_MERGED_REQUEST_ERRORS
        assert row["warmup_errors_total"] == EXPECTED_MERGED_WARMUP_ERRORS
        assert row["error_types"] == {clients[row["client"]]: EXPECTED_MERGED_REQUEST_ERRORS}
        assert row["warmup_error_types"] == {"TimeoutError": EXPECTED_MERGED_WARMUP_ERRORS}
    assert payload["runs"] == expected_runs


def test_isolation_report_keeps_failed_child_diagnostics(tmp_path: Path) -> None:
    args = benchmark_args(tmp_path / "parent")
    results = [
        ChildProcessResult(
            sequence=1,
            client="foghttp",
            scenario=None,
            output_dir=str(tmp_path / "failed-child"),
            report_path=None,
            command=["python", "-m", "foghttp_benchmark"],
            returncode=FAILED_EXIT_CODE,
            duration_s=1.2,
            peaks=ChildResourcePeaks(rss_mb=42.0, threads=3, fds=7),
            stdout_tail="",
            stderr_tail="boom",
        ),
    ]

    write_isolation_report(
        args,
        results,
        {},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((tmp_path / "parent" / "latest.json").read_text())
    child = payload["metadata"]["isolation"]["children"][0]
    assert child["returncode"] == FAILED_EXIT_CODE
    assert child["stderr_tail"] == "boom"
    assert child["peaks"] == {"fds": 7, "rss_mb": 42.0, "threads": 3}
    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["validity"]["reasons"][0]["code"] == "isolated_child_failed"
    assert payload["aggregate"] == []
    assert payload["runs"] == []


@pytest.mark.parametrize(
    ("first_scope", "second_scope", "error"),
    [
        ("requests-load-only-v2", "requests-sampler-inclusive-v1", "children disagree on timing scope"),
        ("requests-load-only-v2", None, "Unknown or unsupported timing scope"),
        (None, None, "Unknown or unsupported timing scope"),
        ("future-timing-v99", "future-timing-v99", "Unknown or unsupported timing scope"),
    ],
)
def test_isolation_report_rejects_incompatible_or_unknown_timing(
    tmp_path: Path,
    first_scope: str | None,
    second_scope: str | None,
    error: str,
) -> None:
    children = []
    for sequence, scope in enumerate((first_scope, second_scope), start=1):
        path = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            aggregate=[],
            runs=[],
            skipped={},
        )
        payload = json.loads(path.read_text())
        if scope is None:
            del payload["metadata"]["timing_scope"]
        else:
            payload["metadata"]["timing_scope"] = scope
        path.write_text(json.dumps(payload))
        children.append(child_result(sequence, "foghttp", path))

    with pytest.raises(ValueError, match=error):
        write_isolation_report(
            benchmark_args(tmp_path / "parent"),
            children,
            {},
            finalizer=get_suite("requests").finalize_report,
            child_cooldown_s=CHILD_COOLDOWN_S,
        )
    assert not (tmp_path / "parent" / "latest.json").exists()


def test_isolation_report_preserves_same_explicit_legacy_timing(tmp_path: Path) -> None:
    children = []
    for sequence in range(1, 3):
        path = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            aggregate=[],
            runs=[],
            skipped={},
            extra_metadata={"timing_scope": "requests-sampler-inclusive-v1"},
        )
        children.append(child_result(sequence, "foghttp", path))
    parent = tmp_path / "parent"

    write_isolation_report(
        benchmark_args(parent),
        children,
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    assert json.loads((parent / "latest.json").read_text())["metadata"]["timing_scope"] == (
        "requests-sampler-inclusive-v1"
    )


@pytest.mark.parametrize("stale_declaration", [False, True])
def test_isolation_report_rejects_mixed_streaming_child_scopes(
    tmp_path: Path,
    *,
    stale_declaration: bool,
) -> None:
    children = []
    for sequence, scope in enumerate(("load-only-v2", "legacy-sampler-v1"), start=1):
        path = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            suite=RESPONSE_STREAMING_SUITE,
            aggregate=[streaming_aggregate(scope)],
            runs=[],
            skipped={},
            extra_metadata={
                "timing_scope": "load-only-v2" if stale_declaration else scope,
                "timing_scopes": [scope],
            },
        )
        children.append(child_result(sequence, "foghttp", path))

    error = "rows disagree on timing scope" if stale_declaration else "children disagree on timing scope"
    with pytest.raises(ValueError, match=error):
        write_isolation_report(
            benchmark_args(tmp_path / "parent", suite=RESPONSE_STREAMING_SUITE),
            children,
            {},
            finalizer=get_suite(RESPONSE_STREAMING_SUITE).finalize_report,
            child_cooldown_s=CHILD_COOLDOWN_S,
        )


def test_isolation_report_rejects_contradictory_explicit_run_timing(tmp_path: Path) -> None:
    report = write_child_report(
        tmp_path / "child",
        client="foghttp",
        suite=RESPONSE_STREAMING_SUITE,
        aggregate=[streaming_aggregate("load-only-v2")],
        runs=[streaming_run("legacy-sampler-v1")],
        skipped={},
    )

    with pytest.raises(ValueError, match="rows disagree on timing scope"):
        write_isolation_report(
            benchmark_args(tmp_path / "parent", suite=RESPONSE_STREAMING_SUITE),
            [child_result(1, "foghttp", report)],
            {},
            finalizer=get_suite(RESPONSE_STREAMING_SUITE).finalize_report,
            child_cooldown_s=CHILD_COOLDOWN_S,
        )


def test_isolation_report_preserves_streaming_scopes(tmp_path: Path) -> None:
    shared = {
        "measurement_scope": "shared-client-server-process-v1",
        "streaming_metric_schema_version": 2,
        "bytes_payload_policy": "byte-pattern-0-255-v1",
    }
    children = []
    for sequence, scope in enumerate(("verified-eof-v2", "observed-v1"), start=1):
        report = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            suite=RESPONSE_STREAMING_SUITE,
            aggregate=[],
            runs=[],
            skipped={},
            extra_metadata={**shared, "throughput_scopes": [scope], "timing_scopes": ["load-only-v2"]},
        )
        children.append(child_result(sequence, "foghttp", report))
    parent_dir = tmp_path / "parent"

    write_isolation_report(
        benchmark_args(parent_dir, suite=RESPONSE_STREAMING_SUITE),
        children,
        {},
        finalizer=get_suite(RESPONSE_STREAMING_SUITE).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    metadata = json.loads((parent_dir / "latest.json").read_text())["metadata"]
    assert {key: metadata[key] for key in shared} == shared
    assert metadata["throughput_scopes"] == ["observed-v1", "verified-eof-v2"]
    assert metadata["timing_scopes"] == ["load-only-v2"]


def test_isolation_report_keeps_empty_streaming_child_diagnostics(tmp_path: Path) -> None:
    report = write_child_report(
        tmp_path / "child",
        client="foghttp",
        suite=RESPONSE_STREAMING_SUITE,
        aggregate=[],
        runs=[],
        skipped={"async:foghttp": "unavailable"},
        extra_metadata={"timing_scopes": []},
    )
    parent = tmp_path / "parent"

    write_isolation_report(
        benchmark_args(parent, suite=RESPONSE_STREAMING_SUITE),
        [child_result(1, "foghttp", report)],
        {},
        finalizer=get_suite(RESPONSE_STREAMING_SUITE).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((parent / "latest.json").read_text())
    assert payload["metadata"]["timing_scope"] == "load-only-v2"
    assert payload["metadata"]["timing_scopes"] == []
    assert payload["metadata"]["skipped"] == {"async:foghttp": "unavailable"}
    assert payload["aggregate"] == []
    assert payload["runs"] == []


@pytest.mark.parametrize(
    "changed_field",
    ["measurement_scope", "streaming_metric_schema_version", "bytes_payload_policy"],
)
@pytest.mark.parametrize("missing", [False, True])
def test_isolation_report_rejects_inconsistent_streaming_contracts(
    tmp_path: Path,
    changed_field: str,
    *,
    missing: bool,
) -> None:
    contract: dict[str, object] = {
        "measurement_scope": "shared-client-server-process-v1",
        "streaming_metric_schema_version": 2,
        "bytes_payload_policy": "byte-pattern-0-255-v1",
    }
    changed = dict(contract)
    if missing:
        del changed[changed_field]
    else:
        changed[changed_field] = "different-contract"
    children = []
    for sequence, metadata in enumerate((contract, changed), start=1):
        report = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            suite=RESPONSE_STREAMING_SUITE,
            aggregate=[],
            runs=[],
            skipped={},
            extra_metadata=metadata,
        )
        children.append(child_result(sequence, "foghttp", report))

    error = (
        "metadata.streaming_metric_schema_version must be an integer"
        if changed_field == "streaming_metric_schema_version" and not missing
        else f"children disagree on {changed_field}"
    )
    with pytest.raises(ValueError, match=error):
        write_isolation_report(
            benchmark_args(tmp_path / "parent", suite=RESPONSE_STREAMING_SUITE),
            children,
            {},
            finalizer=get_suite(RESPONSE_STREAMING_SUITE).finalize_report,
            child_cooldown_s=CHILD_COOLDOWN_S,
        )


@pytest.mark.parametrize("changed_field", [None, "missing", "manifest", "installation", "package_sources"])
def test_isolation_report_checks_every_child_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str | None,
) -> None:
    provenance = {
        "manifest_sha256": "manifest-checksum",
        "manifest": {"foghttp_sha": "release-source-sha", "wheel_sha256": "wheel-checksum"},
        "installation": {"native_sha256": "native-checksum", "python_executable": "/isolated/bin/python"},
    }
    sources = {"foghttp": {"source_type": "installed", "module_file": "/isolated/foghttp/__init__.py"}}
    monkeypatch.setattr(validity_reports, "research_provenance_from_env", lambda: provenance)
    monkeypatch.setattr(validity_reports, "package_sources", lambda _names: sources)
    first_metadata: dict[str, object] = {"research_provenance": provenance, "package_sources": sources}
    second_metadata = json.loads(json.dumps(first_metadata))
    if changed_field == "missing":
        del second_metadata["research_provenance"]
    elif changed_field == "manifest":
        second_metadata["research_provenance"]["manifest"]["wheel_sha256"] = "another-wheel"
    elif changed_field == "installation":
        second_metadata["research_provenance"]["installation"]["native_sha256"] = "another-native"
    elif changed_field == "package_sources":
        second_metadata["package_sources"]["foghttp"]["module_file"] = "/old/foghttp/__init__.py"
    children: list[ChildProcessResult] = []
    for sequence, extra_metadata in enumerate((first_metadata, second_metadata), start=1):
        scenario = f"provenance-child-{sequence}"
        report = write_child_report(
            tmp_path / f"child-{sequence}",
            client="foghttp",
            aggregate=[dict(request_aggregate("foghttp"), scenario=scenario)],
            runs=[dict(request_run("foghttp", repeat=sequence), scenario=scenario)],
            skipped={},
            extra_metadata=extra_metadata,
        )
        children.append(child_result(sequence, "foghttp", report))

    parent_dir = tmp_path / "parent"
    write_isolation_report(
        benchmark_args(parent_dir),
        children,
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((parent_dir / "latest.json").read_text())
    metadata = payload["metadata"]
    assert metadata["research_provenance"] == provenance
    assert metadata["package_sources"] == sources
    child_diagnostics = metadata["isolation"]["children"]
    assert child_diagnostics[0]["research_provenance"] == provenance
    assert child_diagnostics[1]["package_sources"] == second_metadata["package_sources"]
    assert len(payload["aggregate"]) == CHILD_COUNT
    assert len(payload["runs"]) == CHILD_COUNT
    validity = metadata["validity"]
    if changed_field is None:
        assert validity["status"] == "valid"
        assert validity["can_compare"] is True
    else:
        assert validity["status"] == "invalid"
        assert validity["can_compare"] is False
        reason = validity["reasons"][0]
        expected_code = (
            "isolated_child_provenance_missing" if changed_field == "missing" else "isolated_child_provenance_mismatch"
        )
        assert reason["code"] == expected_code
        assert reason["row"]["sequence"] == CHILD_COUNT


def test_isolation_report_preserves_provenance_when_merging_saved_reports(tmp_path: Path) -> None:
    provenance = {"manifest_sha256": "checksum", "manifest": {"sha": "source"}, "installation": {"native": "hash"}}
    sources = {"foghttp": {"source_type": "installed"}}
    report = write_child_report(
        tmp_path / "child",
        client="foghttp",
        aggregate=[],
        runs=[],
        skipped={},
        extra_metadata={"research_provenance": provenance, "package_sources": sources},
    )
    parent_dir = tmp_path / "parent"

    write_isolation_report(
        benchmark_args(parent_dir),
        [child_result(1, "foghttp", report)],
        {},
        finalizer=get_suite("requests").finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    metadata = json.loads((parent_dir / "latest.json").read_text())["metadata"]
    assert metadata["research_provenance"] == provenance
    assert metadata["package_sources"] == sources
    assert metadata["isolation"]["children"][0]["research_provenance"] == provenance


def test_proxy_connect_isolated_report_recomputes_direct_ratios_after_merge(tmp_path: Path) -> None:
    direct_report = write_child_report(
        tmp_path / "direct",
        client="foghttp",
        suite=PROXY_CONNECT_SUITE,
        aggregate=[
            proxy_row("direct-https", "direct", "reused-client", ok_req_s=100.0, direct_ratio=1.0),
        ],
        runs=[],
        skipped={},
    )
    cold_report = write_child_report(
        tmp_path / "cold",
        client="foghttp",
        suite=PROXY_CONNECT_SUITE,
        aggregate=[
            proxy_row("proxy-connect-cold", "explicit", "cold-client", ok_req_s=50.0, direct_ratio=None),
        ],
        runs=[],
        skipped={},
    )
    args = benchmark_args(tmp_path / "parent", suite=PROXY_CONNECT_SUITE, isolation="per-client-scenario")

    write_isolation_report(
        args,
        [child_result(1, "foghttp", direct_report), child_result(2, "foghttp", cold_report)],
        {},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=CHILD_COOLDOWN_S,
    )

    payload = json.loads((tmp_path / "parent" / "latest.json").read_text())
    assert payload["metadata"]["isolation"]["unit"] == "client-scenario"
    assert payload["aggregate"][1]["direct_ratio"] == EXPECTED_COLD_DIRECT_RATIO


def write_child_report(
    output_dir: Path,
    *,
    client: str,
    suite: str = REQUESTS_SUITE,
    aggregate: list[dict[str, object]],
    runs: list[dict[str, object]],
    skipped: dict[str, str],
    extra_metadata: dict[str, object] | None = None,
) -> Path:
    output_dir.mkdir(parents=True)
    report = output_dir / "latest.json"
    report.write_text(
        json.dumps(
            {
                "metadata": {
                    "timestamp": "20260607-000000",
                    "server": "child server",
                    "suite": suite,
                    "timing_scope": current_timing_scope(suite),
                    "package_versions": {"foghttp": "0.3.4"},
                    "run_settling": {
                        "cooldown_s": RUN_COOLDOWN_S,
                        "opened_connection_threshold": RUN_COOLDOWN_OPENED_THRESHOLD,
                    },
                    "skipped": skipped,
                    **(extra_metadata or {}),
                },
                "aggregate": aggregate,
                "runs": runs,
            },
        ),
    )
    return report


def proxy_row(
    case: str,
    config: str,
    lifecycle: str,
    *,
    ok_req_s: float,
    direct_ratio: float | None,
) -> dict[str, object]:
    return {
        "case": case,
        "client": "foghttp",
        "concurrency": 1,
        "request_limit": 1,
        "requests": 100,
        "repeats": 1,
        "errors_total": 0,
        "warmup_errors_total": 0,
        "ok_requests_total": 100,
        "group": "https",
        "config": config,
        "direct_ratio": direct_ratio,
        "lifecycle": lifecycle,
        "mode": "async",
        "ok_req_s_median": ok_req_s,
        "target_scheme": "https",
    }


def child_result(sequence: int, client: str, report_path: Path) -> ChildProcessResult:
    return ChildProcessResult(
        sequence=sequence,
        client=client,
        scenario=None,
        output_dir=str(report_path.parent),
        report_path=str(report_path),
        command=["python", "-m", "foghttp_benchmark"],
        returncode=0,
        duration_s=1.0,
        peaks=ChildResourcePeaks(rss_mb=10.0, threads=1, fds=4),
        stdout_tail="",
        stderr_tail="",
    )


def benchmark_args(
    output_dir: Path,
    *,
    suite: str = REQUESTS_SUITE,
    isolation: str = "per-client-scenario",
) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=suite,
        clients="foghttp,httpx,aiohttp",
        modes="async",
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(output_dir),
        scenarios=DEFAULT_SCENARIOS,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
        isolation=isolation,
    )
