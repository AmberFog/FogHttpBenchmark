import asyncio

import pytest

from foghttp_benchmark.one_upstream.cases import one_upstream_cases
from foghttp_benchmark.proxy_connect.cases import proxy_connect_cases
from foghttp_benchmark.proxy_connect.models import ProxyConnectEndpoints
from foghttp_benchmark.request_builder.cases import request_builder_cases
from foghttp_benchmark.resource.scenarios import resource_cases
from foghttp_benchmark.scenarios import scenarios
from foghttp_benchmark.streaming.cases import streaming_cases
from tests.suite_composition.cases import SUITES, SuiteCase
from tests.suite_composition.support import HTTP_URL, PROXY_URL, SECONDARY_URL, SETTLING, TLS_URL, prepare_suite


CASE_MAPS = {
    "resource-backpressure": resource_cases,
    "one-upstream": one_upstream_cases,
    "request-builder": request_builder_cases,
    "response-streaming": streaming_cases,
    "proxy-connect": proxy_connect_cases,
}
DELEGATED_SUITES = [case for case in SUITES if case.work != "run_once"]


@pytest.mark.parametrize("case", DELEGATED_SUITES, ids=lambda case: case.name)
@pytest.mark.parametrize("no_shuffle", [False, True])
def test_suite_forwards_exact_effective_arguments_and_preserves_case_order(
    monkeypatch: pytest.MonkeyPatch,
    case: SuiteCase,
    *,
    no_shuffle: bool,
) -> None:
    harness = prepare_suite(monkeypatch, case, no_shuffle=no_shuffle)

    asyncio.run(getattr(case.module, case.runner)(harness.args))

    expected: dict[str, object] = {
        "clients": harness.clients,
        "base_url": HTTP_URL,
        "repeats": 2,
        "shuffle": not no_shuffle,
        "seed": 41,
        "progress": None,
    }
    if case.name == "client-creation":
        expected.update(
            scenario=scenarios()["json-small"],
            iterations=11,
            client_counts=[4, 2],
            max_redirects=7,
        )
    else:
        case_map = CASE_MAPS[case.name]()
        expected.update(cases=[case_map[name] for name in case.scenarios.split(",")], warmup=5)
        if case.name == "request-builder":
            expected["iterations"] = 11
        else:
            expected.update(concurrency_levels=[3, 1], requests=19)
    expected_skipped = harness.skipped.copy()
    writer_kwargs: dict[str, object] = {}
    if case.name == "resource-backpressure":
        expected.update(clients=[harness.clients[1]], secondary_base_url=SECONDARY_URL, max_redirects=7)
        expected_skipped["sync:httpx"] = "resource-backpressure suite requires FogHTTP stats"
    elif case.name == "one-upstream":
        expected["settling_config"] = SETTLING
        writer_kwargs["settling_config"] = SETTLING
    elif case.name == "proxy-connect":
        del expected["base_url"]
        expected.update(
            endpoints=ProxyConnectEndpoints(
                http_base_url=HTTP_URL,
                https_base_url=TLS_URL,
                proxy_url=PROXY_URL,
                ca_cert_path="controlled-ca.pem",
            ),
            proxy_stats=harness.proxy_stats,
        )
        writer_kwargs["proxy_url"] = PROXY_URL
    harness.work.assert_awaited_once_with(**expected)
    harness.writer.assert_called_once_with(harness.results, expected_skipped, harness.args, **writer_kwargs)
