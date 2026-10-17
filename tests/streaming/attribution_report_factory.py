from dataclasses import asdict
import gc
import json
from pathlib import Path
import time
from unittest.mock import patch

from foghttp_benchmark.attribution_evidence import condition_fingerprint
from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.provenance import package_sources
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.attribution_reports import write_attribution_reports
from foghttp_benchmark.streaming.lifecycle_consume import expected_body_digest
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig


BODY_BYTES = 1024
SOURCE_SHA = "1" * 40


def provenance(sha: str = SOURCE_SHA) -> JsonObject:
    return {
        "manifest_sha256": "a" * 64,
        "manifest": {
            "source": {"sha": sha, "ref": "refs/heads/release/0.4.2"},
            "build": {"profile": "release"},
            "harness": {
                "sha": "3" * 40,
                "diff_sha256": "c" * 64,
                "files_sha256": {"foghttp_benchmark/cli.py": "d" * 64},
                "root": "/source/harness",
                "branch": "baseline",
            },
        },
        "installation": {"native_sha256": "b" * 64},
    }


def config() -> LifecycleConfig:
    return LifecycleConfig(
        body_bytes=BODY_BYTES,
        server_write_bytes=128,
        warmup_rounds=0,
        batches=1,
        rounds_per_batch=1,
        attribution=AttributionConfig(),
    )


def result(repeat: int, *, duration: float = 1.0) -> JsonObject:
    case = LifecycleCase(repeat, "foghttp", "async", "stream-1m", 1, repeat)
    client_pid, server_pid = 100 + repeat, 200 + repeat
    started, finished = 1_000_000_000, 1_000_000_000 + int(duration * 1_000_000_000)
    cpu = {
        role: {
            "pid": pid,
            "user_s": user,
            "system_s": 0.02,
            "total_s": user + 0.02,
            "unavailable_reason": None,
            "before": {"pid": pid, "probe_started_ns": started - 2, "probe_finished_ns": started - 1},
            "after": {"pid": pid, "probe_started_ns": finished + 1, "probe_finished_ns": finished + 2},
            "load_boundary_overhang_ns": 4,
        }
        for role, pid, user in (("client", client_pid, 0.1), ("server", server_pid, 0.3))
    }
    sample: JsonObject = {
        "stream": 1,
        "status": "ok",
        "error": None,
        "duration_ms": duration * 1000,
        "first_item_ms": 0.5,
        "close_return_ms": 0.1,
        "bytes_read": BODY_BYTES,
        "chunks_read": 2,
        "eof": True,
        "status_code": 200,
        "content_length": str(BODY_BYTES),
        "content_encoding": None,
        "transfer_encoding": None,
        "http_version": "HTTP/1.1",
        "sha256": expected_body_digest(BODY_BYTES),
        "verified_success_bytes": BODY_BYTES,
        "distribution": {
            "histogram": [{"size_bytes": 512, "count": 2}],
            "complete": True,
            "observed_count": 2,
            "min_bytes": 512,
            "max_bytes": 512,
        },
        "delivery_samples": [
            {"index": 1, "size_bytes": 512, "gap_ms": None, "offset_ns": 100},
            {"index": 2, "size_bytes": 512, "gap_ms": 0.2, "offset_ns": 200},
        ],
        "gap_samples_ms": [0.2],
        "clock_resolution_s": time.get_clock_info("perf_counter").resolution,
        "clock": "time.perf_counter_ns",
        "trace": [],
    }
    return {
        "case": asdict(case),
        "parent_pid": 10,
        "client_pid": client_pid,
        "server_pid": server_pid,
        "returncode": 0,
        "server_returncode": 0,
        "report_path": f"isolated/{repeat}/client.json",
        "failure": None,
        "failures": [],
        "client_report": {
            "case": asdict(case),
            "worker_pid": client_pid,
            "status": "ok",
            "config": asdict(config()),
            "gc_configuration": {
                "enabled": gc.isenabled(),
                "threshold": list(gc.get_threshold()),
                "explicit_collection_after_client_close": True,
                "automatic_policy_changed": False,
            },
            "metadata": {"research_provenance": provenance(), "package_sources": package_sources(["foghttp"])},
            "errors": [],
            "warmup": {"errors": [], "rounds": 0, "requests": 0, "samples": [], "ok_streams": 0},
            "phases": [],
            "batches": [
                {
                    "batch": 1,
                    "rounds": 1,
                    "requests": 1,
                    "ok_streams": 1,
                    "duration_s": duration,
                    "verified_success_bytes": BODY_BYTES,
                    "total_observed_bytes": BODY_BYTES,
                    "failed_observed_bytes": 0,
                    "bytes_read_total": BODY_BYTES,
                    "chunks_read_total": 2,
                    "samples": [sample],
                    "cpu": cpu,
                    "errors": [],
                    "server_health": {"status": "ok"},
                    "timing": {
                        "load_started_ns": started,
                        "load_finished_ns": finished,
                        "clock": "time.perf_counter_ns",
                        "digest_finalize_duration_ns": 1,
                        "verified_only_after_finalization": True,
                    },
                    "overhead": {
                        "status": "ok",
                        "distribution_complete": True,
                        "scalar_only_s": 0.01,
                        "sha256_only_s": 0.02,
                        "combined_s": 0.03,
                        "reason": None,
                    },
                },
            ],
            "controls": {
                "held_tail": {"status": "ok", "expected_aborts": 1},
                "recovery": {"status": "ok", "latencies_ms": [2.0]},
                "body_wait_cancel": {"status": "ok"},
                "slow_consumer_cancel": {"status": "ok"},
            },
        },
        "resources": {
            "samples": [
                {"role": "client", "pid": client_pid, "rss_bytes": 1000},
                {"role": "server", "pid": server_pid, "rss_bytes": 2000},
            ],
            "sampled_peaks": {
                "client": {"rss_bytes": 1000, "threads": 3, "fds": 4},
                "server": {"rss_bytes": 2000, "threads": 1, "fds": 5},
            },
            "phases": [],
            "cpu_phase_deltas": [],
            "truncated": False,
        },
    }


def write_report(directory: Path, values: list[JsonObject] | None = None, *, with_provenance: bool = False) -> Path:
    results = values if values is not None else [result(repeat) for repeat in range(1, 4)]
    arguments = BenchmarkArgs(
        suite="response-streaming",
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=1,
        warmup=0,
        repeats=len(results),
        max_redirects=5,
        seed=42,
        no_shuffle=True,
        output_dir=str(directory),
        scenarios="stream-1m",
        iterations=1,
        client_counts="1",
    )
    with patch(
        "foghttp_benchmark.validity.reports.research_provenance_from_env",
        return_value=provenance() if with_provenance else None,
    ):
        write_attribution_reports(results, arguments, config(), [LifecycleCase(**item["case"]) for item in results])
    return directory / "latest.json"


def mutate_report(path: Path, *, source_sha: str | None = None, condition: str | None = None) -> None:
    payload = json.loads(path.read_text())
    if source_sha is not None:
        payload["metadata"]["research_provenance"] = provenance(source_sha)
    if condition is not None:
        for target in (payload["metadata"], *payload["aggregate"]):
            target["conditions"]["test_changed_condition"] = condition
            target["condition_fingerprint"] = condition_fingerprint(target["conditions"])
    path.write_text(json.dumps(payload))
