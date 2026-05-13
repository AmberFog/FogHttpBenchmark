__all__ = (
    "ResourceSampler",
    "ResourceSnapshot",
    "resource_delta",
    "resource_int_delta",
    "take_resource_snapshot",
)

import asyncio
from dataclasses import dataclass
import importlib
import resource
import sys
from typing import Any


@dataclass(frozen=True)
class ResourceSnapshot:
    rss_mb: float | None
    threads: int | None
    fds: int | None


class ResourceSampler:
    def __init__(self, interval: float = 0.02) -> None:
        self.interval = interval
        self.peak_rss_mb: float | None = None
        self.peak_threads: int | None = None
        self.peak_fds: int | None = None
        self._process: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def __aenter__(self) -> "ResourceSampler":
        try:
            psutil = importlib.import_module("psutil")
        except ImportError:
            self._process = None
        else:
            self._process = psutil.Process()
        self._running = True
        self._task = asyncio.create_task(self._sample_loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._running = False
        if self._task is not None:
            await self._task
        if self.peak_rss_mb is None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            scale = 1024 * 1024 if sys.platform == "darwin" else 1024
            self.peak_rss_mb = usage.ru_maxrss / scale

    async def _sample_loop(self) -> None:
        while self._running:
            self.sample()
            await asyncio.sleep(self.interval)
        self.sample()

    def sample(self) -> None:
        if self._process is None:
            return
        rss_mb = self._process.memory_info().rss / 1024 / 1024
        threads = self._process.num_threads()
        fds_getter = getattr(self._process, "num_fds", None)
        fds = fds_getter() if fds_getter is not None else None
        self.peak_rss_mb = max(self.peak_rss_mb or 0.0, rss_mb)
        self.peak_threads = max(self.peak_threads or 0, threads)
        if fds is not None:
            self.peak_fds = max(self.peak_fds or 0, fds)


def take_resource_snapshot() -> ResourceSnapshot:
    try:
        psutil = importlib.import_module("psutil")
    except ImportError:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        scale = 1024 * 1024 if sys.platform == "darwin" else 1024
        return ResourceSnapshot(
            rss_mb=usage.ru_maxrss / scale,
            threads=None,
            fds=None,
        )

    process = psutil.Process()
    fds_getter = getattr(process, "num_fds", None)
    return ResourceSnapshot(
        rss_mb=process.memory_info().rss / 1024 / 1024,
        threads=process.num_threads(),
        fds=fds_getter() if fds_getter is not None else None,
    )


def resource_delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return after - before


def resource_int_delta(after: int | None, before: int | None) -> int | None:
    if after is None or before is None:
        return None
    return after - before
