from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from foghttp_benchmark.models import BenchmarkArgs, ClientStats, LoadResult, RunResult, Scenario
from foghttp_benchmark.one_upstream.models import OneUpstreamStats
from foghttp_benchmark.proxy_connect.models import ProxyConnectLoadResult


WORKLOAD_DURATION_S = 2.0
WORKLOAD_CPU_S = 0.5
SAMPLER_ENTER_S = 7.0
SAMPLER_EXIT_S = 20.0
PEAK_RSS_MB = 12.0
PEAK_THREADS = 3
PEAK_FDS = 4


@dataclass
class TimingHarness:
    wall_s: float = 0.0
    cpu_s: float = 0.0
    events: list[str] = field(default_factory=list)
    failure: BaseException | None = None
    failure_phase: str = "measured"
    scenarios: list[Scenario] = field(default_factory=list)
    results: list[RunResult] = field(default_factory=list)

    @asynccontextmanager
    async def server(self) -> AsyncIterator[str]:
        yield "http://benchmark.invalid"

    def write_reports(
        self,
        results: list[RunResult],
        _skipped: dict[str, str],
        _args: BenchmarkArgs,
        **_kwargs: object,
    ) -> None:
        self.results.extend(results)

    async def settle_after_run(self, *_args: object, **_kwargs: object) -> None:
        self.advance("settle", 23.0, 6.0)

    def advance(self, phase: str, wall_s: float, cpu_s: float) -> None:
        self.events.append(phase)
        self.wall_s += wall_s
        self.cpu_s += cpu_s

    def perf_counter(self) -> float:
        return self.wall_s

    def process_time(self) -> float:
        return self.cpu_s

    def collect_garbage(self) -> None:
        self.advance("gc", 19.0, 4.0)

    def client(self, _config: object) -> "FakeClient":
        self.advance("create", 17.0, 3.0)
        return FakeClient(self)

    def sampler(self) -> "FakeSampler":
        return FakeSampler(self, "resources")

    def transport_sampler(self, _client: object) -> "FakeSampler":
        return FakeSampler(self, "transport")

    def load(self, *, collect: bool) -> tuple[list[float], int, dict[str, int]]:
        phase = "measured" if collect else "warmup"
        self.advance(phase, WORKLOAD_DURATION_S if collect else 11.0, WORKLOAD_CPU_S if collect else 2.0)
        if self.failure is not None and self.failure_phase == phase:
            raise self.failure
        return [1.0, 2.0, 3.0, 4.0], 1, {f"{phase}_failure": 1}

    async def request_load(
        self,
        _client: object,
        scenario: Scenario,
        *_args: object,
        collect: bool,
        **_kwargs: object,
    ) -> LoadResult:
        self.scenarios.append(scenario)
        return LoadResult(*self.load(collect=collect))

    async def one_upstream_load(self, *_args: object, collect: bool, **_kwargs: object) -> OneUpstreamStats:
        return OneUpstreamStats(*self.load(collect=collect))

    async def proxy_load(self, *_args: object, collect: bool, **_kwargs: object) -> ProxyConnectLoadResult:
        return ProxyConnectLoadResult(*self.load(collect=collect))

    async def recovery(self, **_kwargs: object) -> tuple[bool, None]:
        self.advance("recovery", 13.0, 2.0)
        return True, None


@dataclass
class FakeClient:
    mode: ClassVar[Literal["async"]] = "async"
    harness: TimingHarness

    async def close(self) -> None:
        self.harness.advance("close", 31.0, 5.0)

    def stats(self) -> ClientStats:
        self.harness.advance("stats", 5.0, 1.0)
        return {}


@dataclass
class FakeSampler:
    harness: TimingHarness
    name: str
    peak_rss_mb: float = PEAK_RSS_MB
    peak_threads: int = PEAK_THREADS
    peak_fds: int = PEAK_FDS
    peak_active_requests: int = 1
    peak_pending_requests: int = 2
    peak_buffered_response_bytes: int = 8

    async def __aenter__(self) -> "FakeSampler":
        self.harness.advance(f"{self.name}-enter", SAMPLER_ENTER_S, 1.0)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.harness.advance(f"{self.name}-exit", SAMPLER_EXIT_S, 3.0)
