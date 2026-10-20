import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from foghttp_benchmark import suite_selection
from foghttp_benchmark.application import composition
from foghttp_benchmark.compressed_response import suite as compressed_suite
from foghttp_benchmark.constants import (
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
    DEFAULT_WARMUP,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.models import AsyncClientSpec
from foghttp_benchmark.one_upstream import suite as one_upstream_suite
from foghttp_benchmark.proxy_connect import suite as proxy_suite
from foghttp_benchmark.request_builder import suite as request_builder_suite
from foghttp_benchmark.resource import suite as resource_suite
from foghttp_benchmark.streaming import (
    lifecycle,
    suite as streaming_suite,
)
from tests.cli_defaults.support import benchmark_args, invoke_without_work


@pytest.mark.parametrize(
    "suite",
    [
        RESOURCE_BACKPRESSURE_SUITE,
        ONE_UPSTREAM_SUITE,
        REQUEST_BUILDER_SUITE,
        COMPRESSED_RESPONSE_SUITE,
        RESPONSE_STREAMING_SUITE,
        PROXY_CONNECT_SUITE,
    ],
)
def test_explicit_common_scenarios_are_rejected_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
) -> None:
    args = invoke_without_work(monkeypatch, ["--suite", suite, "--scenarios", DEFAULT_SCENARIOS])
    available = Mock(return_value=([AsyncClientSpec("foghttp", Mock())], {}))
    for module, name in (
        (suite_selection, "available_clients"),
        (one_upstream_suite, "available_one_upstream_clients"),
        (request_builder_suite, "available_request_builder_clients"),
        (streaming_suite, "available_streaming_clients"),
        (proxy_suite, "available_proxy_connect_clients"),
    ):
        monkeypatch.setattr(module, name, available)
    server = Mock(side_effect=AssertionError("invalid parameters must fail before server startup"))
    for module in (
        resource_suite,
        one_upstream_suite,
        request_builder_suite,
        streaming_suite,
        proxy_suite,
        compressed_suite,
    ):
        monkeypatch.setattr(module, "benchmark_server", server)

    with pytest.raises(ValueError, match=r"unknown .*cases|unknown scenarios"):
        asyncio.run(composition.run_benchmark_suite(args))

    server.assert_not_called()


@pytest.mark.parametrize("suite", [RESPONSE_STREAMING_SUITE, PROXY_CONNECT_SUITE])
@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("requests", "0", "requests must be >= 1"),
        ("warmup", "-1", "warmup must be >= 0"),
        ("concurrency", "0", "concurrency values must be >= 1"),
        ("concurrency", "invalid", "invalid integer list"),
    ],
)
def test_explicit_invalid_numbers_remain_invalid_before_work(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    name: str,
    value: str,
    message: str,
) -> None:
    case = "stream-1m" if suite == RESPONSE_STREAMING_SUITE else "proxy-connect"
    args = invoke_without_work(monkeypatch, ["--suite", suite, "--scenarios", case, f"--{name}", value])
    available = Mock(return_value=([object()], {}))
    monkeypatch.setattr(streaming_suite, "available_streaming_clients", available)
    monkeypatch.setattr(proxy_suite, "available_proxy_connect_clients", available)
    server = Mock(side_effect=AssertionError("invalid parameters must fail before server startup"))
    monkeypatch.setattr(streaming_suite, "benchmark_server", server)
    monkeypatch.setattr(proxy_suite, "benchmark_server", server)

    with pytest.raises(ValueError, match=message):
        asyncio.run(composition.run_benchmark_suite(args))

    server.assert_not_called()


@pytest.mark.parametrize("profile", ["lifecycle", "async-bytes"])
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("requests", DEFAULT_REQUESTS),
        ("warmup", DEFAULT_WARMUP),
        ("iterations", DEFAULT_CREATION_ITERATIONS),
    ],
)
def test_explicit_common_profile_values_cannot_bypass_existing_caps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str,
    name: str,
    value: int,
) -> None:
    args = invoke_without_work(
        monkeypatch,
        ["--suite", RESPONSE_STREAMING_SUITE, "--streaming-profile", profile, f"--{name}", str(value)],
    )
    launch = AsyncMock()
    monkeypatch.setattr(lifecycle, "run_lifecycle_case", launch)

    with pytest.raises(ValueError, match="request cap"):
        asyncio.run(lifecycle.run_lifecycle_profile(replace(args, output_dir=str(tmp_path))))

    launch.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
