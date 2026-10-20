import pytest

from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
    DEFAULT_CONCURRENCY,
    DEFAULT_ONE_UPSTREAM_SCENARIOS,
    DEFAULT_PROXY_CONNECT_CONCURRENCY,
    DEFAULT_PROXY_CONNECT_REQUESTS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_PROXY_CONNECT_WARMUP,
    DEFAULT_REQUEST_BUILDER_SCENARIOS,
    DEFAULT_REQUESTS,
    DEFAULT_RESOURCE_SCENARIOS,
    DEFAULT_SCENARIOS,
    DEFAULT_STREAMING_REQUESTS,
    DEFAULT_STREAMING_SCENARIOS,
    DEFAULT_WARMUP,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    REQUESTS_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from tests.cli_defaults.support import benchmark_args, invoke_without_work


@pytest.mark.parametrize(
    ("suite", "requests", "warmup", "concurrency", "scenarios"),
    [
        (REQUESTS_SUITE, DEFAULT_REQUESTS, DEFAULT_WARMUP, DEFAULT_CONCURRENCY, DEFAULT_SCENARIOS),
        (CLIENT_CREATION_SUITE, DEFAULT_REQUESTS, DEFAULT_WARMUP, DEFAULT_CONCURRENCY, DEFAULT_SCENARIOS),
        (
            RESOURCE_BACKPRESSURE_SUITE,
            DEFAULT_REQUESTS,
            DEFAULT_WARMUP,
            DEFAULT_CONCURRENCY,
            DEFAULT_RESOURCE_SCENARIOS,
        ),
        (ONE_UPSTREAM_SUITE, DEFAULT_REQUESTS, DEFAULT_WARMUP, DEFAULT_CONCURRENCY, DEFAULT_ONE_UPSTREAM_SCENARIOS),
        (
            REQUEST_BUILDER_SUITE,
            DEFAULT_REQUESTS,
            DEFAULT_WARMUP,
            DEFAULT_CONCURRENCY,
            DEFAULT_REQUEST_BUILDER_SCENARIOS,
        ),
        (
            COMPRESSED_RESPONSE_SUITE,
            DEFAULT_REQUESTS,
            DEFAULT_WARMUP,
            DEFAULT_CONCURRENCY,
            DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
        ),
        (
            RESPONSE_STREAMING_SUITE,
            DEFAULT_STREAMING_REQUESTS,
            DEFAULT_WARMUP,
            DEFAULT_CONCURRENCY,
            DEFAULT_STREAMING_SCENARIOS,
        ),
        (
            PROXY_CONNECT_SUITE,
            DEFAULT_PROXY_CONNECT_REQUESTS,
            DEFAULT_PROXY_CONNECT_WARMUP,
            DEFAULT_PROXY_CONNECT_CONCURRENCY,
            DEFAULT_PROXY_CONNECT_SCENARIOS,
        ),
    ],
)
def test_omitted_options_resolve_to_suite_defaults_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    suite: str,
    requests: int,
    warmup: int,
    concurrency: str,
    scenarios: str,
) -> None:
    args = invoke_without_work(monkeypatch, ["--suite", suite])

    assert args == benchmark_args(
        suite=suite,
        requests=requests,
        warmup=warmup,
        concurrency=concurrency,
        scenarios=scenarios,
    )


@pytest.mark.parametrize(
    ("profile", "modes", "scenarios"),
    [
        ("lifecycle", "async,sync", "first-chunk-close-1m,stream-1m"),
        ("async-bytes", "async", "stream-1m"),
    ],
)
def test_omitted_options_resolve_to_profile_defaults_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    modes: str,
    scenarios: str,
) -> None:
    args = invoke_without_work(
        monkeypatch,
        ["--suite", RESPONSE_STREAMING_SUITE, "--streaming-profile", profile],
    )

    assert args == benchmark_args(
        suite=RESPONSE_STREAMING_SUITE,
        streaming_profile=profile,
        clients="foghttp,httpx",
        modes=modes,
        concurrency="1,10",
        requests=20,
        warmup=2,
        iterations=5,
        repeats=3,
        scenarios=scenarios,
    )
