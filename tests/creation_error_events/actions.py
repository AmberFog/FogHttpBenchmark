import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from foghttp_benchmark.creation import operations_async, operations_sync
from foghttp_benchmark.creation_reports import write_creation_reports
from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.models import (
    AsyncClientSpec,
    BenchmarkArgs,
    ClientConfig,
    ClientCreationResult,
    Scenario,
    SyncClientSpec,
)
from tests.creation_error_events.cases import CreationFailureCase
from tests.creation_error_events.stubs import FailingAsyncClient, FailingSyncClient, snapshot_failure
from tests.isolation.args_factory import benchmark_args


CONFIG = ClientConfig(concurrency=1, request_limit=0, follow_redirects=False, max_redirects=0)
SCENARIO = Scenario(name="offline", method="GET", path="/offline")
OFFLINE_URL = "http://offline.invalid/offline"


def run_failure_case(case: CreationFailureCase, mode: str, monkeypatch: pytest.MonkeyPatch) -> ClientCreationResult:
    module = operations_async if mode == "async" else operations_sync
    if case.snapshot_failure:
        monkeypatch.setattr(module, "take_resource_snapshot", snapshot_failure)
    return asyncio.run(run_async_case(case)) if mode == "async" else run_sync_case(case)


def run_sync_case(case: CreationFailureCase) -> ClientCreationResult:
    spec = SyncClientSpec("offline", lambda _config: FailingSyncClient(case))
    if case.scenario == "create-close":
        return operations_sync.run_sync_create_close(spec, CONFIG, case.iterations, 1)
    if case.scenario == "many-clients-open-close":
        return operations_sync.run_sync_many_clients(spec, CONFIG, case.client_count, 1)
    operation = (
        operations_sync.run_sync_create_first_request
        if case.scenario == "create-first-request"
        else operations_sync.run_sync_reused_request
    )
    return operation(spec, CONFIG, SCENARIO, OFFLINE_URL, iterations=case.iterations, repeat=1)


async def run_async_case(case: CreationFailureCase) -> ClientCreationResult:
    spec = AsyncClientSpec("offline", lambda _config: FailingAsyncClient(case))
    if case.scenario == "create-close":
        return await operations_async.run_async_create_close(spec, CONFIG, case.iterations, 1)
    if case.scenario == "many-clients-open-close":
        return await operations_async.run_async_many_clients(spec, CONFIG, case.client_count, 1)
    operation = (
        operations_async.run_async_create_first_request
        if case.scenario == "create-first-request"
        else operations_async.run_async_reused_request
    )
    return await operation(spec, CONFIG, SCENARIO, OFFLINE_URL, iterations=case.iterations, repeat=1)


def creation_args(directory: Path) -> BenchmarkArgs:
    return replace(benchmark_args(directory), suite="client-creation", clients="offline")


def write_failure_child(directory: Path, result: ClientCreationResult) -> ChildProcessResult:
    write_creation_reports([result, replace(result, repeat=2)], {}, creation_args(directory))
    return ChildProcessResult(
        sequence=1,
        client=result.client,
        scenario=result.scenario,
        output_dir=str(directory),
        report_path=str(directory / "latest.json"),
        command=["offline-test"],
        returncode=0,
        duration_s=result.duration_s,
        peaks=ChildResourcePeaks(rss_mb=None, threads=None, fds=None),
        stdout_tail="offline diagnostic stdout",
        stderr_tail="offline diagnostic stderr",
    )
