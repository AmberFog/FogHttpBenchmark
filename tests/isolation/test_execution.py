import asyncio
from pathlib import Path

from pytest import MonkeyPatch

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
    REQUESTS_SUITE,
)
from foghttp_benchmark.isolation import execution
from foghttp_benchmark.isolation.models import (
    ChildProcessResult,
    ChildResourcePeaks,
    ClientIsolationPlanItem,
    ClientIsolationSelection,
)
from foghttp_benchmark.models import BenchmarkArgs


def test_isolated_benchmark_waits_between_child_processes(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    args = benchmark_args(tmp_path)
    plan = [
        plan_item(1, tmp_path / "child-1"),
        plan_item(2, tmp_path / "child-2"),
        plan_item(3, tmp_path / "child-3"),
    ]
    cooldowns: list[None] = []
    reports: list[list[ChildProcessResult]] = []

    async def fake_wait_between_children(_progress: object) -> None:
        cooldowns.append(None)

    def fake_run_child_process(
        item: ClientIsolationPlanItem,
        *,
        env: dict[str, str] | None = None,
    ) -> ChildProcessResult:
        return child_result(item)

    monkeypatch.setattr(
        execution,
        "select_clients_for_isolation",
        lambda _args: ClientIsolationSelection(["foghttp"], {}),
    )
    monkeypatch.setattr(execution, "build_isolation_plan", lambda _args, _clients: plan)
    monkeypatch.setattr(execution, "run_child_process", fake_run_child_process)
    monkeypatch.setattr(execution, "wait_between_children", fake_wait_between_children)
    monkeypatch.setattr(
        execution,
        "write_isolation_report",
        lambda _args, child_results, _skipped: reports.append(child_results),
    )

    asyncio.run(execution.run_isolated_benchmark(args, progress=None))

    assert len(cooldowns) == len(plan) - 1
    assert [result.sequence for result in reports[0]] == [1, 2, 3]


def plan_item(sequence: int, output_dir: Path) -> ClientIsolationPlanItem:
    return ClientIsolationPlanItem(
        sequence=sequence,
        client="foghttp",
        scenario="json-small",
        output_dir=output_dir,
        command=["python", "-m", "foghttp_benchmark._child"],
    )


def child_result(item: ClientIsolationPlanItem) -> ChildProcessResult:
    report_path = item.output_dir / "latest.json"
    return ChildProcessResult(
        sequence=item.sequence,
        client=item.client,
        scenario=item.scenario,
        output_dir=str(item.output_dir),
        report_path=str(report_path),
        command=item.command,
        returncode=0,
        duration_s=0.1,
        peaks=ChildResourcePeaks(rss_mb=None, threads=None, fds=None),
        stdout_tail="",
        stderr_tail="",
    )


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=REQUESTS_SUITE,
        clients="foghttp",
        modes="async",
        concurrency=DEFAULT_CONCURRENCY,
        requests=DEFAULT_REQUESTS,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=True,
        output_dir=str(output_dir),
        scenarios=DEFAULT_SCENARIOS,
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
