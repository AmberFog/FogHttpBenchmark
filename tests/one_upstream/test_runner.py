import asyncio

import pytest

from foghttp_benchmark.constants import ASYNC_MODE
from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.one_upstream import runner
from foghttp_benchmark.one_upstream.models import OneUpstreamCase, OneUpstreamClientSpec
from foghttp_benchmark.run_settling import RunSettlingConfig


CUSTOM_COOLDOWN_S = 1.0
CUSTOM_THRESHOLD = 256


def test_one_upstream_runner_settles_after_high_connection_churn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[ClientStats | None] = []

    async def fake_settle_after_run(
        client_stats: ClientStats | None,
        _config: RunSettlingConfig,
        **_kwargs: object,
    ) -> None:
        calls.append(client_stats)

    monkeypatch.setattr(runner, "settle_after_run", fake_settle_after_run)
    spec = OneUpstreamClientSpec(
        name="foghttp",
        mode=ASYNC_MODE,
        factory=lambda _config: FakeAsyncOneUpstreamAdapter(),
    )

    results = asyncio.run(
        runner.run_one_upstream_benchmarks(
            clients=[spec],
            base_url="http://127.0.0.1:1",
            cases=[OneUpstreamCase(name="direct-get", group="get", profile="direct", method="GET")],
            concurrency_levels=[1],
            requests=1,
            warmup=0,
            repeats=1,
            shuffle=False,
            seed=1,
            settling_config=RunSettlingConfig(
                cooldown_s=CUSTOM_COOLDOWN_S,
                opened_connection_threshold=CUSTOM_THRESHOLD,
            ),
            progress=None,
        ),
    )

    assert len(results) == 1
    assert results[0].client_stats == {"connections_opened": 300}
    assert calls == [{"connections_opened": 300}]


class FakeAsyncOneUpstreamAdapter:
    async def request(self, _case: OneUpstreamCase, _base_url: str) -> bool:
        return True

    async def close(self) -> None:
        return None

    def stats(self) -> ClientStats:
        return {"connections_opened": 300}
