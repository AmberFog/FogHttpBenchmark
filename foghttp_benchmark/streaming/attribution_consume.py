__all__ = ("ChunkObservations", "ObservationBudget", "PendingStream", "consume_attribution_stream")

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import hashlib
from http import HTTPStatus
import time
from typing import Protocol, cast

from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.attribution_payloads import (
    ChunkDistribution,
    ChunkObservationPayload,
    DeliverySample,
    DiagnosticTrace,
    FinalizedStreamSample,
    ObservationBudgetPayload,
    StreamError,
)
from foghttp_benchmark.streaming.protocols import AsyncStreamClient, AsyncStreamResponse


class _Digest(Protocol):
    def update(self, chunk: bytes | memoryview) -> None: ...

    def hexdigest(self) -> str: ...


class _SizedResponse(Protocol):
    def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]: ...


@dataclass(slots=True)
class ObservationBudget:
    record_cap: int = 4096
    histogram_bins_cap: int = 4096
    records: int = 0
    histogram_bins: int = 0
    global_histogram: dict[int, int] | None = None
    global_histogram_complete: bool = True

    def take_record(self) -> bool:
        if self.records >= self.record_cap:
            return False
        self.records += 1
        return True

    def take_histogram_bin(self) -> bool:
        if self.histogram_bins >= self.histogram_bins_cap:
            return False
        self.histogram_bins += 1
        return True

    def payload(self) -> ObservationBudgetPayload:
        return {
            "record_cap": self.record_cap,
            "records": self.records,
            "histogram_bins_cap": self.histogram_bins_cap,
            "histogram_bins": self.histogram_bins,
            "scope": (
                "Shared per batch across all streams; delivery and diagnostic trace records share one cap; "
                "histogram bins count unique sizes across the whole timed window"
                if self.global_histogram is not None
                else "Shared per batch across all streams; delivery and diagnostic trace records share one cap"
            ),
        }


@dataclass(slots=True)
class ChunkObservations:
    config: AttributionConfig
    budget: ObservationBudget | None = None
    bytes_read: int = 0
    chunks_read: int = 0
    empty_deliveries: int = 0
    first_ns: int | None = None
    previous_ns: int | None = None
    min_bytes: int | None = None
    max_bytes: int | None = None
    histogram: dict[int, int] = field(default_factory=dict)
    histogram_complete: bool = True
    delivery_samples: list[DeliverySample] = field(default_factory=list)
    trace: list[DiagnosticTrace] = field(default_factory=list)

    def observe(self, chunk: bytes | memoryview, arrived_ns: int, started_ns: int) -> None:
        size = len(chunk)
        if not size:
            self.empty_deliveries += 1
            return
        self.bytes_read += size
        self.chunks_read += 1
        self.min_bytes = size if self.min_bytes is None else min(self.min_bytes, size)
        self.max_bytes = size if self.max_bytes is None else max(self.max_bytes, size)
        if self.budget is not None and self.budget.global_histogram is not None:
            histogram = self.budget.global_histogram
            if size in histogram or self.budget.take_histogram_bin():
                histogram[size] = histogram.get(size, 0) + 1
            else:
                self.budget.global_histogram_complete = False
        elif size in self.histogram or (
            len(self.histogram) < self.config.histogram_bins_cap
            and (self.budget is None or self.budget.take_histogram_bin())
        ):
            self.histogram[size] = self.histogram.get(size, 0) + 1
        else:
            self.histogram_complete = False
        if self.first_ns is None:
            self.first_ns = arrived_ns
        gap = (arrived_ns - self.previous_ns) / 1_000_000 if self.previous_ns is not None else None
        if len(self.delivery_samples) < self.config.chunk_sample_cap and (
            self.budget is None or self.budget.take_record()
        ):
            self.delivery_samples.append(
                {
                    "index": self.chunks_read,
                    "size_bytes": size,
                    "gap_ms": gap,
                    "offset_ns": arrived_ns - started_ns,
                },
            )
        self.previous_ns = arrived_ns

    def payload(self) -> ChunkObservationPayload:
        global_budget = self.budget is not None and self.budget.global_histogram is not None
        distribution: ChunkDistribution = {
            "histogram": [{"size_bytes": size, "count": count} for size, count in sorted(self.histogram.items())],
            "complete": (
                self.budget.global_histogram_complete if global_budget and self.budget else self.histogram_complete
            ),
            "observed_count": self.chunks_read,
            "min_bytes": self.min_bytes,
            "max_bytes": self.max_bytes,
            "bins_cap": self.config.histogram_bins_cap,
        }
        if global_budget:
            distribution["scope"] = "batch-global"
        return {
            "bytes_read": self.bytes_read,
            "chunks_read": self.chunks_read,
            "empty_deliveries": self.empty_deliveries,
            "distribution": distribution,
            "delivery_samples": self.delivery_samples,
            "gap_samples_ms": [item["gap_ms"] for item in self.delivery_samples if item["gap_ms"] is not None],
            "delivery_sample_count": len(self.delivery_samples),
            "delivery_samples_truncated": self.chunks_read > len(self.delivery_samples),
            "delivery_samples_dropped": self.chunks_read - len(self.delivery_samples),
            "sampling_rule": (
                "first N nonempty deliveries per stream until the shared batch cap; "
                "adjacent arrival gaps, no extrapolation"
            ),
            "chunk_sample_cap": self.config.chunk_sample_cap,
            "clock": "time.perf_counter_ns; monotonic; gap milliseconds and offset nanoseconds",
            "clock_resolution_s": time.get_clock_info("perf_counter").resolution,
            "gap_scope": "Public Python delivery to delivery, including prior hashing/bookkeeping/consumer delay",
            "trace": self.trace,
            "trace_samples_dropped": (
                self.chunks_read - len(self.trace) if self.config.instrumentation == "diagnostic" else 0
            ),
            "trace_scope": (
                "Diagnostic public anext await and harness consumer timestamps; not native wakeups or copies"
                if self.config.instrumentation == "diagnostic"
                else "Disabled for control instrumentation"
            ),
        }


@dataclass(slots=True)
class PendingStream:
    stream: int
    observations: ChunkObservations
    digest: _Digest
    started_ns: int
    finished_ns: int = 0
    close_started_ns: int | None = None
    eof: bool = False
    status_code: int | None = None
    content_length: str | None = None
    content_encoding: str | None = None
    transfer_encoding: str | None = None
    http_version: str | None = None
    error: StreamError | None = None

    def finalize(self, *, body_bytes: int, expected_digest: str) -> FinalizedStreamSample:
        # Finalization deliberately follows the enclosing batch's wall/CPU end.
        digest = self.digest.hexdigest()
        error = self.error
        if error is None:
            message = self._integrity_error(body_bytes, digest, expected_digest)
            if message:
                error = {"type": "IntegrityError", "message": message}
        observations = self.observations
        return {
            "stream": self.stream,
            "status": "ok" if error is None else "failed",
            "error": error,
            "duration_ms": (self.finished_ns - self.started_ns) / 1_000_000,
            "first_item_ms": (
                (observations.first_ns - self.started_ns) / 1_000_000 if observations.first_ns is not None else None
            ),
            "close_return_ms": (
                (self.finished_ns - self.close_started_ns) / 1_000_000 if self.close_started_ns is not None else None
            ),
            "eof": self.eof,
            "status_code": self.status_code,
            "content_length": self.content_length,
            "content_encoding": self.content_encoding,
            "transfer_encoding": self.transfer_encoding,
            "http_version": self.http_version,
            "sha256": digest,
            "verified_success_bytes": observations.bytes_read if error is None else 0,
            **observations.payload(),
        }

    def _integrity_error(self, body_bytes: int, digest: str, expected_digest: str) -> str | None:
        if self.status_code != HTTPStatus.OK or self.content_length != str(body_bytes):
            return "Response status or Content-Length differs from the declared workload"
        if self.transfer_encoding is not None or self.http_version not in {"HTTP/1.1", "1.1"}:
            return "Response must use HTTP/1.1 Content-Length framing"
        if self.content_encoding is not None:
            return "Response must be uncompressed with no Content-Encoding header"
        if not self.eof or self.observations.bytes_read != body_bytes or digest != expected_digest:
            return "Response failed complete-body EOF/length/SHA-256 integrity validation"
        return None


def _headers(result: PendingStream, response: AsyncStreamResponse) -> None:
    result.status_code = int(response.status_code)
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    for name in ("content_length", "content_encoding", "transfer_encoding"):
        value = getter(name.replace("_", "-")) if callable(getter) else None
        setattr(result, name, str(value) if value is not None else None)
    version = getattr(response, "http_version", None)
    result.http_version = str(version) if version is not None else None


async def consume_attribution_stream(
    client: AsyncStreamClient,
    url: str,
    *,
    body_bytes: int,
    stream: int,
    config: AttributionConfig,
    budget: ObservationBudget | None = None,
) -> PendingStream:
    observations = ChunkObservations(config, budget)
    result = PendingStream(stream, observations, hashlib.sha256(), time.perf_counter_ns())
    try:
        async with client.stream("GET", url) as response:
            _headers(result, response)
            iterator = (
                response.aiter_bytes()
                if config.requested_client_read_bytes is None
                else cast("_SizedResponse", response).aiter_bytes(chunk_size=config.requested_client_read_bytes)
            )
            try:
                await _consume_iterator(iterator, result, body_bytes=body_bytes)
            finally:
                result.close_started_ns = time.perf_counter_ns()
    except Exception as error:  # noqa: BLE001 - preserve failed partial deliveries for the explicit integrity verdict.
        result.error = {"type": type(error).__name__, "message": str(error)}
    finally:
        result.finished_ns = time.perf_counter_ns()
    return result


async def _consume_iterator(iterator: AsyncIterator[bytes], result: PendingStream, *, body_bytes: int) -> None:
    observations = result.observations
    config = observations.config
    while True:
        await_started = time.perf_counter_ns() if config.instrumentation == "diagnostic" else None
        try:
            chunk = await anext(iterator)
        except StopAsyncIteration:
            result.eof = True
            return
        arrived = time.perf_counter_ns()
        observations.observe(chunk, arrived, result.started_ns)
        if not chunk:
            continue
        result.digest.update(chunk)
        if observations.bytes_read > body_bytes:
            msg = "Public iterator exceeded declared payload size"
            raise ValueError(msg)
        if config.consumer_delay_s and observations.bytes_read < body_bytes:
            await asyncio.sleep(config.consumer_delay_s)
        if (
            await_started is not None
            and len(observations.trace) < config.chunk_sample_cap
            and (observations.budget is None or observations.budget.take_record())
        ):
            observations.trace.append(
                {
                    "index": observations.chunks_read,
                    "await_start_ns": await_started,
                    "await_finished_ns": arrived,
                    "consumer_finished_ns": time.perf_counter_ns(),
                },
            )
