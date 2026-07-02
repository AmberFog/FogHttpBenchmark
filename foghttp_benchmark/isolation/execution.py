__all__ = ("run_isolated_benchmark",)

import asyncio
from dataclasses import replace
import os

from foghttp_benchmark.isolation.models import (
    PER_CLIENT_SCENARIO_ISOLATION,
    ChildProcessResult,
    ClientIsolationPlanItem,
)
from foghttp_benchmark.isolation.planning import build_client_isolation_plan, build_client_scenario_isolation_plan
from foghttp_benchmark.isolation.process import run_child_process
from foghttp_benchmark.isolation.reports import write_isolation_report
from foghttp_benchmark.isolation.scenarios import scenario_names_for_isolation
from foghttp_benchmark.isolation.selection import select_clients_for_isolation
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.progress import ProgressReporter, progress_stage, progress_status


CHILD_PROCESS_COOLDOWN_S = 5.0


async def run_isolated_benchmark(args: BenchmarkArgs, *, progress: ProgressReporter | None = None) -> None:
    args = replace(args, isolation=PER_CLIENT_SCENARIO_ISOLATION)

    progress_status(progress, "Selecting clients for subprocess isolation")
    selection = select_clients_for_isolation(args)
    if not selection.clients:
        msg = f"No requested clients are available for isolated run: {selection.skipped}"
        raise ValueError(msg)

    plan = build_isolation_plan(args, selection.clients)
    progress_status(progress, f"Starting {len(plan)} sequential isolated child processes")
    child_results: list[ChildProcessResult] = []
    env = os.environ.copy()
    with progress_stage(progress, "Isolated child processes", total=len(plan), plain_output="heartbeat") as step:
        for item_index, item in enumerate(plan):
            step.update(plan_label(item, total=len(plan)))
            result = run_child_process(item, env=env)
            child_results.append(result)
            step.advance(f"{plan_label(item, total=len(plan))} exit={result.returncode}")
            if item_index < len(plan) - 1:
                await wait_between_children(progress)

    progress_status(progress, "Writing isolated benchmark report")
    write_isolation_report(args, child_results, selection.skipped)
    failures = failed_children(child_results)
    if failures:
        msg = "Isolated benchmark child process failed: " + ", ".join(
            f"{result.client} exit={result.returncode}" for result in failures
        )
        raise ValueError(msg)


async def wait_between_children(progress: ProgressReporter | None) -> None:
    progress_status(progress, f"Waiting {CHILD_PROCESS_COOLDOWN_S:.1f}s before next isolated child")
    await asyncio.sleep(CHILD_PROCESS_COOLDOWN_S)


def failed_children(results: list[ChildProcessResult]) -> list[ChildProcessResult]:
    return [result for result in results if result.returncode != 0 or result.report_path is None]


def build_isolation_plan(args: BenchmarkArgs, clients: list[str]) -> list[ClientIsolationPlanItem]:
    scenarios = scenario_names_for_isolation(args)
    if scenarios:
        return build_client_scenario_isolation_plan(args, clients, scenarios)
    return build_client_isolation_plan(args, clients)


def plan_label(item: ClientIsolationPlanItem, *, total: int) -> str:
    if item.scenario is None:
        return f"{item.sequence}/{total} {item.client}"
    return f"{item.sequence}/{total} {item.client}/{item.scenario}"
