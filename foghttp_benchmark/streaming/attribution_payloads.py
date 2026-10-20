__all__ = (
    "AttributionBatch",
    "BatchStreamError",
    "BatchTiming",
    "ChunkDistribution",
    "ChunkObservationPayload",
    "CpuDelta",
    "CpuRole",
    "CpuSnapshot",
    "CpuSnapshotInProgress",
    "DeliverySample",
    "DiagnosticTrace",
    "FinalizedStreamSample",
    "HistogramBin",
    "ObservationBudgetPayload",
    "StreamError",
)

from typing import Literal, NotRequired, TypedDict

from foghttp_benchmark.models import JsonObject


CpuRole = Literal["client", "server"]


class _CpuSnapshotFields(TypedDict):
    pid: int
    probe_started_ns: int
    user_s: float | None
    system_s: float | None
    reason: str | None


class CpuSnapshot(_CpuSnapshotFields):
    probe_finished_ns: int


class CpuSnapshotInProgress(_CpuSnapshotFields):
    probe_finished_ns: NotRequired[int]


class CpuDelta(TypedDict):
    pid: int
    user_s: float | None
    system_s: float | None
    total_s: float | None
    cpu_seconds_per_verified_byte: float | None
    cpu_seconds_per_wall_second: float | None
    unavailable_reason: str | None
    normalization_unavailable_reason: str | None
    before: CpuSnapshot
    after: CpuSnapshot
    load_boundary_overhang_ns: int
    scope: str
    resolution_s: None
    resolution_unavailable_reason: str
    cpu_wall_interpretation: str


class DeliverySample(TypedDict):
    index: int
    size_bytes: int
    gap_ms: float | None
    offset_ns: int


class DiagnosticTrace(TypedDict):
    index: int
    await_start_ns: int
    await_finished_ns: int
    consumer_finished_ns: int


class HistogramBin(TypedDict):
    size_bytes: int
    count: int


class ChunkDistribution(TypedDict):
    histogram: list[HistogramBin]
    complete: bool
    observed_count: int
    min_bytes: int | None
    max_bytes: int | None
    bins_cap: int
    scope: NotRequired[str]


class ChunkObservationPayload(TypedDict):
    bytes_read: int
    chunks_read: int
    empty_deliveries: int
    distribution: ChunkDistribution
    delivery_samples: list[DeliverySample]
    gap_samples_ms: list[float]
    delivery_sample_count: int
    delivery_samples_truncated: bool
    delivery_samples_dropped: int
    sampling_rule: str
    chunk_sample_cap: int
    clock: str
    clock_resolution_s: float
    gap_scope: str
    trace: list[DiagnosticTrace]
    trace_samples_dropped: int
    trace_scope: str


class StreamError(TypedDict):
    type: str
    message: str


class FinalizedStreamSample(ChunkObservationPayload):
    stream: int
    status: Literal["ok", "failed"]
    error: StreamError | None
    duration_ms: float
    first_item_ms: float | None
    close_return_ms: float | None
    eof: bool
    status_code: int | None
    content_length: str | None
    content_encoding: str | None
    transfer_encoding: str | None
    http_version: str | None
    sha256: str
    verified_success_bytes: int


class BatchStreamError(StreamError):
    stream: int


class ObservationBudgetPayload(TypedDict):
    record_cap: int
    records: int
    histogram_bins_cap: int
    histogram_bins: int
    scope: str
    total_deliveries: NotRequired[int]
    recorded_delivery_samples: NotRequired[int]
    dropped_delivery_samples: NotRequired[int]
    recorded_trace_samples: NotRequired[int]
    dropped_trace_samples: NotRequired[int]
    histogram_complete: NotRequired[bool]


class BatchTiming(TypedDict):
    load_started_ns: int
    load_finished_ns: int
    clock: str
    clock_resolution_s: float
    scope: str
    digest_finalize_duration_ns: int
    verified_only_after_finalization: bool


class AttributionBatch(TypedDict):
    batch: int
    rounds: int
    requests: int
    ok_streams: int
    duration_s: float
    streams_per_second: float | None
    ok_streams_per_second: float | None
    verified_success_bytes: int
    total_observed_bytes: int
    failed_observed_bytes: int
    bytes_read_total: int
    chunks_read_total: int
    verified_bytes_per_second: float | None
    mb_per_second: float | None
    expected_aborts: int
    errors: list[BatchStreamError]
    samples: list[FinalizedStreamSample]
    observation_budget: ObservationBudgetPayload
    cpu: dict[CpuRole, CpuDelta]
    timing: BatchTiming
    overhead: JsonObject
    attribution_limits: JsonObject
    python_profile: NotRequired[JsonObject]
    window: NotRequired[JsonObject]
    server_before: NotRequired[JsonObject]
    server_delivery: NotRequired[JsonObject]
    server_health: NotRequired[JsonObject]
