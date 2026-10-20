import pytest

from foghttp_benchmark.constants import (
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_STREAMING_SCENARIOS,
    RESPONSE_STREAMING_SUITE,
)
from tests.cli_defaults.support import capture_streaming_execution, invoke_without_work


def test_response_streaming_report_args_record_effective_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    args = invoke_without_work(monkeypatch, ["--suite", RESPONSE_STREAMING_SUITE])

    called, reported_args = capture_streaming_execution(monkeypatch, args)

    assert called["requests"] == DEFAULT_STREAMING_REQUESTS
    assert reported_args.requests == DEFAULT_STREAMING_REQUESTS
    assert [case.name for case in called["cases"]] == DEFAULT_STREAMING_SCENARIOS.split(",")
    assert reported_args.scenarios == DEFAULT_STREAMING_SCENARIOS
    assert reported_args == args
