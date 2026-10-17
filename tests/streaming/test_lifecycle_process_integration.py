import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark.isolation.lifecycle import run_lifecycle_case
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from foghttp_benchmark.streaming.lifecycle_reports import write_lifecycle_reports
from tests.streaming.lifecycle_profile_factory import lifecycle_args


DISTINCT_ROLES = 3
CORRECTNESS_BODY_BYTES = 16_384
CORRECTNESS_WRITE_BYTES = 1024
CASE_OUTER_TIMEOUT_S = 15


@pytest.mark.parametrize("client", ["foghttp", "httpx"])
@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("concurrency", [1, 10])
@pytest.mark.parametrize("scenario", ["stream-1m", "first-chunk-close-1m"])
def test_isolated_worker_server_and_report_contract(
    tmp_path: Path,
    client: str,
    mode: str,
    concurrency: int,
    scenario: str,
) -> None:
    case = LifecycleCase(1, client, mode, scenario, concurrency, 1)
    config = LifecycleConfig(
        body_bytes=CORRECTNESS_BODY_BYTES,
        server_write_bytes=CORRECTNESS_WRITE_BYTES,
        warmup_rounds=0,
        batches=1,
        rounds_per_batch=1,
        case_timeout_s=10,
    )
    receipt = asyncio.run(asyncio.wait_for(run_lifecycle_case(case, config, tmp_path / "case"), CASE_OUTER_TIMEOUT_S))

    assert receipt["status"] == "ok", receipt
    assert len({receipt["parent_pid"], receipt["client_pid"], receipt["server_pid"]}) == DISTINCT_ROLES
    assert receipt["client_report"]["worker_pid"] == receipt["client_pid"]
    assert receipt["client_report"]["controls"]["held_tail"]["expected_aborts"] == concurrency
    assert receipt["resources"]["units"]["rss_bytes"] == "bytes"
    assert receipt["resources"]["units"]["cpu_user_s"] == "seconds"
    assert receipt["resources"]["truncated"] is False
    for sample in receipt["resources"]["samples"]:
        assert sample["pid"] == receipt[f"{sample['role']}_pid"]
        if sample["process_terminated"]:
            assert sample["rss_bytes"] is None
            assert sample["termination_reason"]
        else:
            assert sample["rss_bytes"] > 0
    assert {delta["role"] for delta in receipt["resources"]["cpu_phase_deltas"]} == {"client", "server"}

    args = replace(
        lifecycle_args(tmp_path / "report"),
        clients=client,
        modes=mode,
        concurrency=str(concurrency),
        scenarios=scenario,
    )
    write_lifecycle_reports([receipt], args, config, [case])
    parent = json.loads((tmp_path / "report/latest.json").read_text())

    assert parent["metadata"]["validity"]["status"] == "valid", parent["metadata"]["validity"]
    assert parent["metadata"]["measurement_scope"] == "separate-client-server-pids-v1"
    assert parent["runs"][0] == receipt
    assert "rss_mb_max" not in parent["aggregate"][0]
    assert (tmp_path / "report/latest.md").is_file()
