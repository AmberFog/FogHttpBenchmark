import json
from pathlib import Path

from foghttp_benchmark.compare.loading import load_benchmark_report


EXPECTED_STREAMS_PER_SECOND = 100.0


def test_compare_loads_response_streaming_report(tmp_path: Path) -> None:
    report_path = tmp_path / "streaming.json"
    report_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "suite": "response-streaming",
                    "timestamp": "20260526-120000",
                    "package_versions": {"foghttp": "0.3.1"},
                },
                "aggregate": [
                    {
                        "mode": "async",
                        "client": "foghttp",
                        "case": "stream-64k",
                        "consume": "all",
                        "concurrency": 10,
                        "request_limit": 10,
                        "ok_streams_s_median": EXPECTED_STREAMS_PER_SECOND,
                        "p95_ms_median": 1.2,
                        "p99_ms_median": 2.3,
                        "errors_total": 0,
                        "warmup_errors_total": 0,
                        "error_rate_percent": 0.0,
                        "rss_mb_max": 10.0,
                        "threads_max": 4,
                        "fds_max": 12,
                    },
                ],
            },
        ),
    )

    report = load_benchmark_report(report_path)

    assert report.suite == "response-streaming"
    assert report.rows[0].identity == ("async", "foghttp", "stream-64k", "bytes", "all", "10", "10")
    assert report.rows[0].primary_value == EXPECTED_STREAMS_PER_SECOND
