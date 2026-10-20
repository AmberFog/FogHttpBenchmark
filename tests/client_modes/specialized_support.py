from dataclasses import dataclass
from typing import Literal

from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.one_upstream.cases import one_upstream_cases
from foghttp_benchmark.one_upstream.models import (
    AsyncOneUpstreamClientSpec,
    OneUpstreamResult,
    SyncOneUpstreamClientSpec,
)
from foghttp_benchmark.one_upstream.runner import run_one_upstream_case
from foghttp_benchmark.proxy_connect.cases import proxy_connect_cases
from foghttp_benchmark.proxy_connect.models import (
    AsyncProxyConnectClientSpec,
    ProxyConnectEndpoints,
    ProxyConnectResult,
    SyncProxyConnectClientSpec,
)
from foghttp_benchmark.proxy_connect.proxy_server import ProxyServerStats
from foghttp_benchmark.proxy_connect.runner import run_proxy_connect_case
from foghttp_benchmark.streaming.cases import streaming_cases
from foghttp_benchmark.streaming.models import (
    AsyncStreamingClientSpec,
    StreamingCase,
    StreamingOutcome,
    StreamingResult,
    SyncStreamingClientSpec,
)
from foghttp_benchmark.streaming.runner import run_streaming_case
from tests.client_modes.support import ClientEvents


Suite = Literal["streaming", "one-upstream", "proxy-connect"]


@dataclass
class SpecializedEvents(ClientEvents):
    available_stats: ClientStats | None = None

    def stats(self) -> ClientStats | None:
        self.record("stats")
        if self.stats_failure:
            message = "injected stats failure"
            raise RuntimeError(message)
        return self.available_stats

    def response(self) -> bool:
        self.record("request")
        return True

    def stream(self, case: StreamingCase) -> StreamingOutcome:
        self.record("stream")
        return StreamingOutcome(
            status_code=200,
            bytes_read=case.size_bytes,
            chunks_read=1,
            first_chunk_ms=0.1,
            body_sha256=case.expected_sha256,
            eof_received=True,
        )


class AsyncSpecializedClient:
    mode: Literal["async"] = "async"

    def __init__(self, events: SpecializedEvents) -> None:
        self.events = events

    async def request(self, _case: object, _url: str) -> bool:
        return self.events.response()

    async def stream(self, case: StreamingCase, _url: str) -> StreamingOutcome:
        return self.events.stream(case)

    async def close(self) -> None:
        self.events.record("close")

    def stats(self) -> ClientStats | None:
        return self.events.stats()


class SyncSpecializedClient:
    mode: Literal["sync"] = "sync"

    def __init__(self, events: SpecializedEvents) -> None:
        self.events = events

    def request(self, _case: object, _url: str) -> bool:
        return self.events.response()

    def stream(self, case: StreamingCase, _url: str) -> StreamingOutcome:
        return self.events.stream(case)

    def close(self) -> None:
        self.events.record("close")

    def stats(self) -> ClientStats | None:
        return self.events.stats()


async def run_specialized_case(
    suite: Suite,
    mode: str,
    events: SpecializedEvents,
) -> StreamingResult | OneUpstreamResult | ProxyConnectResult:
    def make_async(_config: object) -> AsyncSpecializedClient:
        events.before_create()
        return AsyncSpecializedClient(events)

    def make_sync(_config: object) -> SyncSpecializedClient:
        events.before_create()
        return SyncSpecializedClient(events)

    if suite == "streaming":
        return await run_streaming_case(
            spec=AsyncStreamingClientSpec("fake", make_async)
            if mode == "async"
            else SyncStreamingClientSpec("fake", make_sync),
            base_url="http://benchmark.invalid",
            case=streaming_cases()["stream-64k"],
            concurrency=1,
            requests=2,
            warmup=1,
            repeat=1,
        )
    if suite == "one-upstream":
        return await run_one_upstream_case(
            spec=AsyncOneUpstreamClientSpec("fake", make_async)
            if mode == "async"
            else SyncOneUpstreamClientSpec("fake", make_sync),
            base_url="http://benchmark.invalid",
            case=one_upstream_cases()["direct-get"],
            concurrency=1,
            requests=2,
            warmup=1,
            repeat=1,
        )
    return await run_proxy_connect_case(
        spec=AsyncProxyConnectClientSpec("fake", make_async)
        if mode == "async"
        else SyncProxyConnectClientSpec("fake", make_sync),
        endpoints=ProxyConnectEndpoints(
            "http://benchmark.invalid",
            "https://benchmark.invalid",
            "http://proxy.invalid",
            "unused.crt",
        ),
        proxy_stats=ProxyServerStats(),
        case=proxy_connect_cases()["direct-http"],
        concurrency=1,
        requests=2,
        warmup=1,
        repeat=1,
    )
