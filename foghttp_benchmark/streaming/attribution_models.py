__all__ = ("AttributionConfig", "validate_attribution_config")

from dataclasses import dataclass
import math
from typing import Literal

from foghttp_benchmark.perf_evidence import DEFAULT_PERF_SAMPLE_FREQUENCY_HZ, PERF_SAMPLE_FREQUENCIES_HZ


MAX_BODY_BYTES = 1_048_576
MAX_PROFILER_LABEL = 128
MIN_WINDOW_STREAMS = 20
MAX_WINDOW_STREAMS = 2048
MAX_WINDOW_DURATION_S = 5
MAX_HISTOGRAM_BINS = 1024
MAX_REPLAY_SEGMENTS = 64


@dataclass(frozen=True, slots=True)
class AttributionConfig:
    server_delay_s: float = 0.0
    requested_client_read_bytes: int | None = None
    consumer_delay_s: float = 0.0
    instrumentation: Literal["control", "diagnostic"] = "control"
    profiler_label: str | None = None
    profiler: Literal["none", "cprofile", "sample-client", "sample-server", "perf-client", "perf-server"] = "none"
    perf_sample_frequency_hz: int = DEFAULT_PERF_SAMPLE_FREQUENCY_HZ
    chunk_sample_cap: int = 128
    histogram_bins_cap: int = 1024
    replay_max_bytes: int = 268_435_456
    replay_max_chunks: int = 1_000_000
    minimum_duration_s: float = 0.0
    max_window_streams: int = 2048
    server_observations: bool = False


def validate_attribution_config(config: AttributionConfig, *, client: str | None = None) -> None:
    _validate_window(config)
    for name in ("server_delay_s", "consumer_delay_s"):
        value = getattr(config, name)
        maximum_s = 0.1 if name == "server_delay_s" else 1.0
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or not 0 <= value <= maximum_s
        ):
            msg = f"{name} must be finite and between zero and {maximum_s} seconds"
            raise ValueError(msg)
    _validate_observations(config, client=client)


def _validate_window(config: AttributionConfig) -> None:
    duration = config.minimum_duration_s
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or (duration != 0 and not 1 <= duration <= MAX_WINDOW_DURATION_S)
    ):
        msg = "Minimum load duration must be zero (fixed rounds) or between 1 and 5 seconds"
        raise ValueError(msg)
    if (
        type(config.max_window_streams) is not int
        or not MIN_WINDOW_STREAMS <= config.max_window_streams <= MAX_WINDOW_STREAMS
    ):
        msg = "A duration window requires a hard limit between 20 and 2048 complete streams"
        raise ValueError(msg)
    server_observations: object = config.server_observations
    if type(server_observations) is not bool:
        msg = "Server body observations must be boolean"
        raise ValueError(msg)


def _validate_observations(config: AttributionConfig, *, client: str | None) -> None:
    _validate_profiler(config)
    size = config.requested_client_read_bytes
    if size is not None and (type(size) is not int or not 1 <= size <= MAX_BODY_BYTES):
        msg = "Requested public client read size must be null/native or an integer within 1 MiB"
        raise ValueError(msg)
    if size is not None and client is not None and client != "httpx":
        msg = "Explicit client read size is supported only by HTTPX; FogHTTP must use its native public iterator"
        raise ValueError(msg)
    if config.instrumentation not in {"control", "diagnostic"}:
        msg = "Instrumentation must be control or diagnostic"
        raise ValueError(msg)
    if config.profiler_label is not None and (
        config.instrumentation != "diagnostic"
        or not isinstance(config.profiler_label, str)
        or not config.profiler_label.strip()
        or len(config.profiler_label) > MAX_PROFILER_LABEL
    ):
        msg = "A bounded nonempty profiler label requires diagnostic instrumentation"
        raise ValueError(msg)
    for name, maximum in (
        ("chunk_sample_cap", 128),
        ("histogram_bins_cap", 1024),
        ("replay_max_bytes", 268_435_456),
        ("replay_max_chunks", 1_000_000),
    ):
        value = getattr(config, name)
        if type(value) is not int or not 1 <= value <= maximum:
            msg = f"{name} must be a positive integer no greater than {maximum}"
            raise ValueError(msg)


def _validate_profiler(config: AttributionConfig) -> None:
    if config.profiler not in {"none", "cprofile", "sample-client", "sample-server", "perf-client", "perf-server"}:
        msg = "Profiler must be none, cprofile, sample-client, sample-server, perf-client or perf-server"
        raise ValueError(msg)
    if config.profiler != "none" and (config.instrumentation != "diagnostic" or not config.profiler_label):
        msg = "An active profiler requires diagnostic instrumentation and a profiler label"
        raise ValueError(msg)
    frequency = config.perf_sample_frequency_hz
    if type(frequency) is not int or frequency not in PERF_SAMPLE_FREQUENCIES_HZ:
        msg = "Perf sampling frequency must be 499 or 1999 Hz"
        raise ValueError(msg)
    if frequency != DEFAULT_PERF_SAMPLE_FREQUENCY_HZ and config.profiler not in {"perf-client", "perf-server"}:
        msg = "A nondefault perf sampling frequency requires an active perf profiler"
        raise ValueError(msg)
