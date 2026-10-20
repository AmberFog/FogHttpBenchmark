import asyncio

import pytest

from foghttp_benchmark.compressed_response.scenarios import compressed_response_scenarios
from foghttp_benchmark.scenarios import scenarios
from tests.suite_composition.cases import SUITES, SuiteCase
from tests.suite_composition.support import HTTP_URL, SETTLING, prepare_suite


REQUEST_SUITES = [case for case in SUITES if case.work == "run_once"]
# Frozen seed=41 order for two requested scenarios, [3, 1], two clients and two repeats.
SHUFFLED_ORDER = (
    (0, 3, "httpx", 2),
    (1, 1, "foghttp", 2),
    (1, 3, "foghttp", 2),
    (0, 3, "httpx", 1),
    (0, 1, "foghttp", 2),
    (1, 1, "foghttp", 1),
    (1, 1, "httpx", 2),
    (1, 3, "foghttp", 1),
    (1, 3, "httpx", 1),
    (0, 1, "httpx", 1),
    (1, 3, "httpx", 2),
    (0, 1, "foghttp", 1),
    (0, 3, "foghttp", 1),
    (0, 3, "foghttp", 2),
    (0, 1, "httpx", 2),
    (1, 1, "httpx", 1),
)


@pytest.mark.parametrize("case", REQUEST_SUITES, ids=lambda case: case.name)
@pytest.mark.parametrize("no_shuffle", [False, True])
def test_request_suite_uses_declared_plan_and_settles_each_completed_run(
    monkeypatch: pytest.MonkeyPatch,
    case: SuiteCase,
    *,
    no_shuffle: bool,
) -> None:
    harness = prepare_suite(monkeypatch, case, no_shuffle=no_shuffle)

    asyncio.run(getattr(case.module, case.runner)(harness.args))

    requested = case.scenarios.split(",")
    scenario_map = scenarios() if case.name == "requests" else compressed_response_scenarios()
    client_map = {client.name: client for client in harness.clients}
    order = (
        [
            (index, concurrency, client, repeat)
            for index in range(2)
            for concurrency in (3, 1)
            for client in ("httpx", "foghttp")
            for repeat in (1, 2)
        ]
        if no_shuffle
        else list(SHUFFLED_ORDER)
    )
    assert harness.work.await_count == len(order)
    for call, (index, concurrency, client, repeat) in zip(harness.work.await_args_list, order, strict=True):
        scenario = scenario_map[requested[index]]
        spec = client_map[client]
        assert call.args == ()
        assert call.kwargs == {
            "spec": spec,
            "base_url": HTTP_URL,
            "scenario": scenario,
            "concurrency": concurrency,
            "requests": 19,
            "repeat": repeat,
            "warmup": 5,
            "max_redirects": 7,
            "progress": None,
            "progress_label": f"{spec.mode}/{client} {scenario.name} concurrency={concurrency} repeat={repeat}/2",
        }
    assert harness.events == [
        "enter:http",
        *[event for _ in order for event in ("run", "settle")],
        "exit:http",
        "write",
    ]
    assert harness.settle is not None
    assert harness.settle.await_count == len(order)
    for call in harness.settle.await_args_list:
        assert call.args == (harness.stats, SETTLING)
        assert call.kwargs == {"progress": None}
    harness.writer.assert_called_once_with(
        [harness.results[0]] * len(order),
        harness.skipped,
        harness.args,
        settling_config=SETTLING,
    )
