from collections.abc import AsyncIterator
from typing import Literal, Self

from foghttp_benchmark.models import ClientStats
from foghttp_benchmark.server import benchmark_server
from foghttp_benchmark.streaming.cases import streaming_cases
from foghttp_benchmark.streaming.factories import make_httpx_async
from foghttp_benchmark.streaming.models import (
    AsyncStreamingClientSpec,
    StreamingCase,
    StreamingLoadResult,
    StreamingOutcome,
    StreamingResult,
)
from foghttp_benchmark.streaming.runner import run_streaming_case


class OutcomeSource:
    def __init__(self, outcomes: list[StreamingOutcome | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.closed = False

    def next_outcome(self) -> StreamingOutcome:
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def stats(self) -> ClientStats | None:
        return None


class AsyncOutcomeClient(OutcomeSource):
    mode: Literal["async"] = "async"

    async def stream(self, _case: StreamingCase, _url: str) -> StreamingOutcome:
        return self.next_outcome()

    async def close(self) -> None:
        self.closed = True


class SyncOutcomeClient(OutcomeSource):
    mode: Literal["sync"] = "sync"

    def stream(self, _case: StreamingCase, _url: str) -> StreamingOutcome:
        return self.next_outcome()

    def close(self) -> None:
        self.closed = True


async def async_chunks(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


class LoadClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def load(self, *_args: object, collect: bool, **_kwargs: object) -> StreamingLoadResult:
        if collect:
            self.value += 2.0
        return StreamingLoadResult([], [], 0, 0, 0, 0, 0, {})


class SlowExitSampler:
    peak_rss_mb: float | None = None
    peak_threads: int | None = None
    peak_fds: int | None = None

    def __init__(self, clock: LoadClock) -> None:
        self.clock = clock

    async def __aenter__(self) -> Self:
        self.clock.value += 7.0
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.clock.value += 20.0


async def run_controlled_http_stream() -> StreamingResult:
    async with benchmark_server() as base_url:
        return await run_streaming_case(
            spec=AsyncStreamingClientSpec("httpx", make_httpx_async),
            base_url=base_url,
            case=streaming_cases()["stream-64k"],
            concurrency=1,
            requests=1,
            warmup=0,
            repeat=1,
        )
