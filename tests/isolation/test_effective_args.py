from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from foghttp_benchmark._child import build_child_args, build_parser
from foghttp_benchmark.application.composition import get_suite
from foghttp_benchmark.constants import (
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
    REQUESTS_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.isolation.models import ChildProcessResult, ChildResourcePeaks
from foghttp_benchmark.isolation.planning import benchmark_child_command
from foghttp_benchmark.isolation.reports import write_isolation_report
from tests.isolation.args_factory import benchmark_args
from tests.isolation.effective_args_support import write_empty_child_report


@pytest.mark.parametrize("suite", [REQUESTS_SUITE, RESPONSE_STREAMING_SUITE, PROXY_CONNECT_SUITE])
@pytest.mark.parametrize("warmup", [DEFAULT_WARMUP, 0])
def test_child_and_parent_reports_preserve_effective_workload_parameters(
    tmp_path: Path,
    suite: str,
    warmup: int,
) -> None:
    args = replace(benchmark_args(tmp_path), suite=suite, warmup=warmup)
    output_dir = tmp_path / "child"
    command = benchmark_child_command(args, client="httpx", output_dir=output_dir)
    child_args = build_child_args(build_parser().parse_args(command[3:]))
    write_empty_child_report(child_args)
    child_result = ChildProcessResult(
        sequence=1,
        client="httpx",
        scenario=None,
        output_dir=str(output_dir),
        report_path=str(output_dir / "latest.json"),
        command=command,
        returncode=0,
        duration_s=0.0,
        peaks=ChildResourcePeaks(rss_mb=None, threads=None, fds=None),
        stdout_tail="",
        stderr_tail="",
    )

    write_isolation_report(
        args,
        [child_result],
        {},
        finalizer=get_suite(args.suite).finalize_report,
        child_cooldown_s=1.0,
    )

    parent_report = json.loads((tmp_path / "latest.json").read_text())
    child_report = json.loads((output_dir / "latest.json").read_text())
    assert parent_report["metadata"]["args"] == asdict(args)
    assert child_report["metadata"]["args"] == asdict(
        replace(args, clients="httpx", output_dir=str(output_dir)),
    )
