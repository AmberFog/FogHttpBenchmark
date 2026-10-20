import pytest

from foghttp_benchmark.constants import (
    DEFAULT_PROXY_CONNECT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_REQUESTS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_PROXY_CONNECT_WARMUP,
    PROXY_CONNECT_SUITE,
)
from tests.cli_defaults.support import capture_proxy_execution, invoke_without_work


def test_proxy_connect_report_args_record_effective_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    args = invoke_without_work(monkeypatch, ["--suite", PROXY_CONNECT_SUITE])

    called, report_args = capture_proxy_execution(monkeypatch, args)

    assert called["requests"] == DEFAULT_PROXY_CONNECT_REQUESTS
    assert called["warmup"] == DEFAULT_PROXY_CONNECT_WARMUP
    assert called["concurrency_levels"] == [int(value) for value in DEFAULT_PROXY_CONNECT_CONCURRENCY.split(",")]
    assert [case.name for case in called["cases"]] == DEFAULT_PROXY_CONNECT_SCENARIOS.split(",")
    assert report_args.requests == DEFAULT_PROXY_CONNECT_REQUESTS
    assert report_args.warmup == DEFAULT_PROXY_CONNECT_WARMUP
    assert report_args.scenarios == DEFAULT_PROXY_CONNECT_SCENARIOS
    assert report_args.concurrency == DEFAULT_PROXY_CONNECT_CONCURRENCY
    assert report_args == args
