import json
from pathlib import Path

import pytest

from foghttp_benchmark.constants import (
    BENCHMARK_SEED,
    DEFAULT_CLIENT_COUNTS,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_MODES,
    DEFAULT_REPEATS,
    DEFAULT_WARMUP,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs
from foghttp_benchmark.streaming.reports import aggregate_streaming_results, write_streaming_reports
from tests.streaming.factories import streaming_result


EXPECTED_BODY_CLOSED = 11
EXPECTED_BODY_REUSE = 9
EXPECTED_BODY_ABORTED = 3
EXPECTED_CONNECTIONS_OPENED = 2
EXPECTED_CONNECTIONS_REUSED = 10
EXPECTED_CONNECTIONS_CLOSED = 2
EXPECTED_CONNECTIONS_ABORTED = 3


def test_aggregate_streaming_results_keeps_lifecycle_stats() -> None:
    rows = aggregate_streaming_results(
        [
            streaming_result(
                streams_per_second=100.0,
                ok_streams_per_second=100.0,
                mb_per_second=50.0,
                p95_ms=1.0,
                first_chunk_p95_ms=0.5,
                client_stats={
                    "active_requests": 0,
                    "response_body_closed": 10,
                    "response_body_reuse_eligible": 8,
                    "response_body_aborted": 2,
                    "connections_opened": 1,
                    "connections_reused": 9,
                    "connections_closed": 1,
                    "connections_aborted": 2,
                    "idle_connections": 1,
                },
            ),
            streaming_result(
                streams_per_second=120.0,
                ok_streams_per_second=120.0,
                mb_per_second=60.0,
                p95_ms=2.0,
                first_chunk_p95_ms=0.7,
                client_stats={
                    "active_requests": 0,
                    "response_body_closed": 11,
                    "response_body_reuse_eligible": 9,
                    "response_body_aborted": 3,
                    "connections_opened": 2,
                    "connections_reused": 10,
                    "connections_closed": 2,
                    "connections_aborted": 3,
                    "idle_connections": 1,
                },
            ),
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.read == "bytes"
    assert row.streams_s_median == pytest.approx(110.0)
    assert row.ok_streams_s_median == pytest.approx(110.0)
    assert row.mb_s_median == pytest.approx(55.0)
    assert row.lines_s_median == 0.0
    assert row.text_chars_read_total == 0
    assert row.lines_read_total == 0
    assert row.p95_ms_median == pytest.approx(1.5)
    assert row.first_chunk_p95_ms_median == pytest.approx(0.6)
    assert row.final_active_requests_max == 0
    assert row.final_response_body_closed_max == EXPECTED_BODY_CLOSED
    assert row.final_response_body_reuse_eligible_max == EXPECTED_BODY_REUSE
    assert row.final_response_body_aborted_max == EXPECTED_BODY_ABORTED
    assert row.final_connections_opened_max == EXPECTED_CONNECTIONS_OPENED
    assert row.final_connections_reused_max == EXPECTED_CONNECTIONS_REUSED
    assert row.final_connections_closed_max == EXPECTED_CONNECTIONS_CLOSED
    assert row.final_connections_aborted_max == EXPECTED_CONNECTIONS_ABORTED
    assert row.final_idle_connections_max == 1


def test_write_streaming_reports_keeps_installed_foghttp_source_outside_repo_git(tmp_path: Path) -> None:
    write_streaming_reports([], {}, benchmark_args(tmp_path))

    payload = json.loads((tmp_path / "latest.json").read_text())
    foghttp_source = payload["metadata"]["package_sources"]["foghttp"]
    module_file = str(foghttp_source.get("module_file", ""))
    if "site-packages" not in module_file:
        return

    assert foghttp_source["source_type"] == "installed"
    assert "site_packages_root" in foghttp_source
    assert "git_root" not in foghttp_source


def benchmark_args(output_dir: Path) -> BenchmarkArgs:
    return BenchmarkArgs(
        suite=RESPONSE_STREAMING_SUITE,
        clients=DEFAULT_CLIENTS,
        modes=DEFAULT_MODES,
        concurrency=DEFAULT_CONCURRENCY,
        requests=3,
        warmup=DEFAULT_WARMUP,
        repeats=DEFAULT_REPEATS,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        seed=BENCHMARK_SEED,
        no_shuffle=False,
        output_dir=str(output_dir),
        scenarios="stream-64k",
        iterations=DEFAULT_CREATION_ITERATIONS,
        client_counts=DEFAULT_CLIENT_COUNTS,
    )
