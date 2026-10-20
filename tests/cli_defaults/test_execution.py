import pytest

from foghttp_benchmark.constants import (
    DEFAULT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_REQUESTS,
    DEFAULT_PROXY_CONNECT_WARMUP,
    DEFAULT_REQUESTS,
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_WARMUP,
    PROXY_CONNECT_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from tests.cli_defaults.support import benchmark_args, capture_proxy_execution, capture_streaming_execution


@pytest.mark.parametrize("requests", [DEFAULT_REQUESTS, DEFAULT_STREAMING_REQUESTS, 7])
def test_programmatic_streaming_arguments_reach_runner_and_report_without_substitution(
    monkeypatch: pytest.MonkeyPatch,
    requests: int,
) -> None:
    args = benchmark_args(
        suite=RESPONSE_STREAMING_SUITE,
        scenarios="stream-1m",
        requests=requests,
        concurrency="2,3",
        warmup=0,
    )

    called, reported = capture_streaming_execution(monkeypatch, args)

    assert called["requests"] == args.requests
    assert called["warmup"] == args.warmup
    assert called["concurrency_levels"] == [2, 3]
    assert [case.name for case in called["cases"]] == ["stream-1m"]
    assert reported == args


@pytest.mark.parametrize(
    ("requests", "warmup", "concurrency"),
    [
        (DEFAULT_REQUESTS, DEFAULT_WARMUP, DEFAULT_CONCURRENCY),
        (DEFAULT_PROXY_CONNECT_REQUESTS, DEFAULT_PROXY_CONNECT_WARMUP, DEFAULT_PROXY_CONNECT_CONCURRENCY),
        (7, 0, "2,3"),
    ],
    ids=["equal-to-common-defaults", "equal-to-suite-defaults", "custom"],
)
def test_programmatic_proxy_arguments_reach_runner_and_report_without_substitution(
    monkeypatch: pytest.MonkeyPatch,
    requests: int,
    warmup: int,
    concurrency: str,
) -> None:
    args = benchmark_args(
        suite=PROXY_CONNECT_SUITE,
        scenarios="proxy-connect",
        requests=requests,
        warmup=warmup,
        concurrency=concurrency,
    )

    called, reported = capture_proxy_execution(monkeypatch, args)

    assert called["requests"] == args.requests
    assert called["warmup"] == args.warmup
    assert called["concurrency_levels"] == [int(value) for value in args.concurrency.split(",")]
    assert [case.name for case in called["cases"]] == ["proxy-connect"]
    assert reported == args
