import asyncio
from collections import Counter
import threading

import pytest

from foghttp_benchmark import runner
from foghttp_benchmark.creation.constants import (
    CREATE_CLOSE_SCENARIO,
    CREATE_FIRST_REQUEST_SCENARIO,
    MANY_CLIENTS_SCENARIO,
    REUSED_REQUEST_SCENARIO,
)
from foghttp_benchmark.creation.runner import measure_creation_scenario
from foghttp_benchmark.models import ClientConfig, Scenario
from foghttp_benchmark.resource.runner import run_resource_case
from foghttp_benchmark.resource.scenarios import ResourceCase
from tests.client_modes.support import ClientEvents, recorded_spec


SCENARIO = Scenario("fake-bytes", "GET", "/bytes/1", expected_content_length=1)
CONFIG = ClientConfig(concurrency=1, request_limit=1, follow_redirects=False, max_redirects=1)
RESOURCE_REQUESTS_WITH_RECOVERY = 4


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("request_failure", [False, True])
def test_request_mode_preserves_thread_dispatch_close_and_nullable_stats(mode: str, *, request_failure: bool) -> None:
    events = ClientEvents(request_failure=request_failure)
    main_thread = threading.get_ident()
    result = asyncio.run(
        runner.run_once(
            spec=recorded_spec(mode, events),
            base_url="http://benchmark.invalid",
            scenario=SCENARIO,
            concurrency=1,
            requests=2,
            warmup=1,
            repeat=1,
        ),
    )

    assert result.mode == mode
    assert result.client_stats is None
    assert result.errors == (2 if request_failure else 0)
    assert result.warmup_errors == int(request_failure)
    assert result.error_types == ({"ValueError": 2} if request_failure else {})
    assert Counter(name for name, _ in events.events) == {"create": 1, "request": 3, "stats": 1, "close": 1}
    assert events.events[-1] == ("close", main_thread)
    assert all((thread == main_thread) == (mode == "async") for name, thread in events.events if name == "request")


@pytest.mark.parametrize("mode", ["async", "sync"])
def test_request_stats_failure_still_closes_once(mode: str) -> None:
    events = ClientEvents(stats_failure=True)
    with pytest.raises(RuntimeError, match="injected stats failure"):
        asyncio.run(
            runner.run_once(
                spec=recorded_spec(mode, events),
                base_url="http://benchmark.invalid",
                scenario=SCENARIO,
                concurrency=1,
                requests=1,
                warmup=0,
                repeat=1,
            ),
        )
    assert [name for name, _ in events.events] == ["create", "request", "stats", "close"]


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("mixed_origins", [False, True])
def test_resource_mode_preserves_dispatch_recovery_and_unknown_counters(mode: str, *, mixed_origins: bool) -> None:
    events = ClientEvents()
    main_thread = threading.get_ident()
    result = asyncio.run(
        run_resource_case(
            spec=recorded_spec(mode, events),
            base_url="http://primary.invalid",
            secondary_base_url="http://secondary.invalid",
            case=ResourceCase(
                "fake-resource",
                "/bytes/1",
                request_limit=1,
                max_pending_requests=1,
                expected_content_length=1,
                secondary_path="/bytes/1" if mixed_origins else None,
                recovery_path="/bytes/1",
            ),
            concurrency=1,
            requests=2,
            warmup=1,
            repeat=1,
            max_redirects=1,
        ),
    )

    assert result.mode == mode
    assert result.errors == result.warmup_errors == 0
    assert result.recovery_ok is True
    assert result.client_stats is None
    assert result.peak_active_requests is None
    assert result.peak_pending_requests is None
    assert result.peak_buffered_response_bytes is None
    assert Counter(name for name, _ in events.events)["request"] == RESOURCE_REQUESTS_WITH_RECOVERY
    assert Counter(name for name, _ in events.events)["close"] == 1
    assert events.events[-1] == ("close", main_thread)
    assert all((thread == main_thread) == (mode == "async") for name, thread in events.events if name == "request")


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize(
    ("scenario", "clients", "requests"),
    [
        (CREATE_CLOSE_SCENARIO, 2, 0),
        (CREATE_FIRST_REQUEST_SCENARIO, 2, 2),
        (REUSED_REQUEST_SCENARIO, 1, 3),
        (MANY_CLIENTS_SCENARIO, 3, 0),
    ],
)
def test_creation_scenarios_preserve_factory_request_close_and_thread_boundaries(
    mode: str,
    scenario: str,
    clients: int,
    requests: int,
) -> None:
    events = ClientEvents()
    main_thread = threading.get_ident()
    result = asyncio.run(
        measure_creation_scenario(
            recorded_spec(mode, events),
            CONFIG,
            scenario_name=scenario,
            scenario=SCENARIO,
            url="http://benchmark.invalid/bytes/1",
            iterations=2,
            client_count=3,
            repeat=1,
        ),
    )

    assert result.mode == mode
    assert result.errors == 0
    assert result.close_p50_ms is not None
    assert Counter(name for name, _ in events.events) == Counter(create=clients, request=requests, close=clients)
    assert all((thread == main_thread) == (mode == "async") for _, thread in events.events)


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("scenario", [CREATE_FIRST_REQUEST_SCENARIO, REUSED_REQUEST_SCENARIO, MANY_CLIENTS_SCENARIO])
def test_creation_failure_closes_every_successfully_created_client(mode: str, scenario: str) -> None:
    events = ClientEvents(request_failure=True, fail_create_after=1 if scenario == MANY_CLIENTS_SCENARIO else None)
    result = asyncio.run(
        measure_creation_scenario(
            recorded_spec(mode, events),
            CONFIG,
            scenario_name=scenario,
            scenario=SCENARIO,
            url="http://benchmark.invalid/bytes/1",
            iterations=2,
            client_count=3,
            repeat=1,
        ),
    )

    expected_errors = 2 if scenario == CREATE_FIRST_REQUEST_SCENARIO else 1
    assert result.errors == expected_errors
    assert result.error_types == {"ValueError": expected_errors}
    assert Counter(name for name, _ in events.events)["close"] == events.created
