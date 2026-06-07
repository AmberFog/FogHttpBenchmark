import json
from pathlib import Path

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
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
)
from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.models import BenchmarkArgs


CHILD_COUNT = 2
FAILED_EXIT_CODE = 2
EXPECTED_COLD_DIRECT_RATIO = 0.5


def test_isolation_report_merges_successful_child_reports(tmp_path: Path) -> None:
    first_report = write_child_report(
        tmp_path / "child-1",
        client="foghttp",
        aggregate=[{"client": "foghttp", "ok_req_s_median": 100.0}],
        runs=[{"client": "foghttp", "repeat": 1}],
        skipped={},
    )
    second_report = write_child_report(
        tmp_path / "child-2",
        client="httpx",
        aggregate=[{"client": "httpx", "ok_req_s_median": 90.0}],
        runs=[{"client": "httpx", "repeat": 1}],
        skipped={"sync:httpx": "not requested by test"},
    )
    args = benchmark_args(tmp_path / "parent")
    results = [
        child_result(1, "foghttp", first_report),
        child_result(2, "httpx", second_report),
    ]

    write_isolation_report(args, results, {"async:aiohttp": "unsupported in this suite"})

    payload = json.loads((tmp_path / "parent" / "latest.json").read_text())
    metadata = payload["metadata"]
    assert metadata["suite"] == REQUESTS_SUITE
    assert metadata["isolation"]["backend"] == "subprocess"
    assert metadata["isolation"]["scheduler"] == "sequential"
    assert len(metadata["isolation"]["children"]) == CHILD_COUNT
    assert payload["aggregate"] == [
        {"client": "foghttp", "ok_req_s_median": 100.0},
        {"client": "httpx", "ok_req_s_median": 90.0},
    ]
    assert payload["runs"] == [{"client": "foghttp", "repeat": 1}, {"client": "httpx", "repeat": 1}]
    assert metadata["skipped"] == {
        "async:aiohttp": "unsupported in this suite",
        "sync:httpx": "not requested by test",
    }
    assert "subprocess" in (tmp_path / "parent" / "latest.md").read_text()


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

    write_isolation_report(args, results, {})

    payload = json.loads((tmp_path / "parent" / "latest.json").read_text())
    child = payload["metadata"]["isolation"]["children"][0]
    assert child["returncode"] == FAILED_EXIT_CODE
    assert child["stderr_tail"] == "boom"
    assert child["peaks"] == {"fds": 7, "rss_mb": 42.0, "threads": 3}
    assert payload["metadata"]["validity"]["status"] == "invalid"
    assert payload["metadata"]["validity"]["reasons"][0]["code"] == "isolated_child_failed"
    assert payload["aggregate"] == []
    assert payload["runs"] == []


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
            proxy_row("proxy-connect-cold", "explicit-proxy", "cold-client", ok_req_s=50.0, direct_ratio=None),
        ],
        runs=[],
        skipped={},
    )
    args = benchmark_args(tmp_path / "parent", suite=PROXY_CONNECT_SUITE, isolation="per-client-scenario")

    write_isolation_report(
        args,
        [child_result(1, "foghttp", direct_report), child_result(2, "foghttp", cold_report)],
        {},
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
                    "package_versions": {"foghttp": "0.3.4"},
                    "skipped": skipped,
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
