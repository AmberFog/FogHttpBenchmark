from dataclasses import asdict

import pytest

from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_CLIENTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_CREATION_ITERATIONS,
    DEFAULT_MODES,
    DEFAULT_REPEATS,
    DEFAULT_REQUESTS,
    DEFAULT_SCENARIOS,
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
    "suite",
    [
        REQUESTS_SUITE,
        CLIENT_CREATION_SUITE,
        RESOURCE_BACKPRESSURE_SUITE,
        ONE_UPSTREAM_SUITE,
        REQUEST_BUILDER_SUITE,
        COMPRESSED_RESPONSE_SUITE,
        RESPONSE_STREAMING_SUITE,
        PROXY_CONNECT_SUITE,
    ],
)
@pytest.mark.parametrize(
    "overrides",
    [
        {
            "requests": DEFAULT_REQUESTS,
            "warmup": DEFAULT_WARMUP,
            "concurrency": DEFAULT_CONCURRENCY,
            "scenarios": DEFAULT_SCENARIOS,
        },
        {"requests": 7, "warmup": 0, "concurrency": "2,3", "scenarios": "explicit-case"},
    ],
    ids=["equal-to-common-defaults", "custom"],
)
def test_explicit_options_are_literal_for_every_suite(
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    overrides: dict[str, str | int],
) -> None:
    parameters = ["--suite", suite]
    for name, value in overrides.items():
        parameters.extend([f"--{name}", str(value)])

    args = invoke_without_work(monkeypatch, parameters)

    assert args == benchmark_args(suite=suite, **overrides)


@pytest.mark.parametrize("profile", ["lifecycle", "async-bytes"])
@pytest.mark.parametrize(
    ("name", "common", "custom"),
    [
        ("clients", DEFAULT_CLIENTS, "httpx"),
        ("modes", DEFAULT_MODES, "sync"),
        ("concurrency", DEFAULT_CONCURRENCY, "2"),
        ("requests", DEFAULT_REQUESTS, 1),
        ("warmup", DEFAULT_WARMUP, 0),
        ("iterations", DEFAULT_CREATION_ITERATIONS, 1),
        ("repeats", DEFAULT_REPEATS, 1),
        ("scenarios", DEFAULT_SCENARIOS, "stream-64k"),
    ],
)
@pytest.mark.parametrize("use_common", [True, False], ids=["equal-to-common-default", "custom"])
def test_explicit_profile_options_are_never_replaced(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    name: str,
    common: str | int,
    custom: str | int,
    *,
    use_common: bool,
) -> None:
    value = common if use_common else custom
    parameters = ["--suite", RESPONSE_STREAMING_SUITE, "--streaming-profile", profile]
    omitted_args = invoke_without_work(monkeypatch, parameters)

    explicit_args = invoke_without_work(monkeypatch, [*parameters, f"--{name}", str(value)])

    expected = asdict(omitted_args)
    expected[name] = value
    assert asdict(explicit_args) == expected
