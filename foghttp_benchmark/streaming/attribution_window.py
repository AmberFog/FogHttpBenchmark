__all__ = ("window_distribution_matches", "window_workload_matches")

import math

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.attribution_models import (
    MAX_HISTOGRAM_BINS,
    MAX_REPLAY_SEGMENTS,
    MAX_WINDOW_DURATION_S,
    MAX_WINDOW_STREAMS,
    MIN_WINDOW_STREAMS,
)
from foghttp_benchmark.streaming.lifecycle_reports import int_value, number, object_list, object_value


def window_workload_matches(batch: JsonObject, configuration: JsonObject, concurrency: int) -> bool:
    declared = object_value(configuration.get("attribution"))
    window = object_value(batch.get("window"))
    duration = number(batch.get("duration_s"))
    target = number(declared.get("minimum_duration_s"))
    rounds = batch.get("rounds")
    minimum_rounds = configuration.get("rounds_per_batch")
    limit = declared.get("max_window_streams")
    if (
        duration is None
        or target is None
        or not 1 <= target <= MAX_WINDOW_DURATION_S
        or type(limit) is not int
        or not MIN_WINDOW_STREAMS <= limit <= MAX_WINDOW_STREAMS
        or type(rounds) is not int
        or type(minimum_rounds) is not int
        or not minimum_rounds <= rounds <= limit // concurrency
        or window.get("minimum_duration_s") != target
        or window.get("minimum_rounds") != minimum_rounds
        or window.get("max_streams") != limit
        or batch.get("requests") != rounds * concurrency
    ):
        return False
    reached = duration >= target
    return window.get("target_reached") is reached and (
        window.get("stop_reason") == "duration-reached"
        if reached
        else window.get("stop_reason") == "stream-limit" and rounds == limit // concurrency
    )


def window_distribution_matches(batch: JsonObject, configuration: JsonObject) -> bool:
    window = object_value(batch.get("window"))
    distribution = object_value(window.get("global_histogram"))
    attribution = object_value(configuration.get("attribution"))
    body = configuration.get("body_bytes")
    samples = object_list(batch.get("samples"))
    histogram = _histogram(distribution.get("histogram"))
    cap = attribution.get("histogram_bins_cap")
    if (
        type(body) is not int
        or histogram is None
        or type(cap) is not int
        or not 1 <= cap <= MAX_HISTOGRAM_BINS
        or len(histogram) > cap
        or any(size > body for size in histogram)
        or distribution.get("complete") is not True
        or distribution.get("scope") != "batch-global"
        or distribution.get("bins_cap") != cap
        or not samples
    ):
        return False
    chunks = sum(histogram.values())
    observed = sum(size * count for size, count in histogram.items())
    if (
        chunks != sum(int_value(sample.get("chunks_read")) for sample in samples)
        or observed != body * len(samples)
        or distribution.get("observed_count") != chunks
        or distribution.get("observed_bytes") != observed
        or batch.get("chunks_read_total") != chunks
        or batch.get("total_observed_bytes") != observed
    ):
        return False
    if not all(
        object_value(sample.get("distribution")).get("scope") == "batch-global"
        and object_value(sample.get("distribution")).get("histogram") == []
        and object_value(sample.get("distribution")).get("min_bytes") in histogram
        and object_value(sample.get("distribution")).get("max_bytes") in histogram
        and _stream_chunk_bounds_match(sample, body)
        for sample in samples
    ):
        return False
    return _replay_matches(object_value(batch.get("overhead")), histogram, attribution)


def _stream_chunk_bounds_match(sample: JsonObject, body: int) -> bool:
    chunks = sample.get("chunks_read")
    distribution = object_value(sample.get("distribution"))
    minimum, maximum = distribution.get("min_bytes"), distribution.get("max_bytes")
    return (
        type(chunks) is int
        and 1 <= chunks <= body
        and type(minimum) is int
        and type(maximum) is int
        and 1 <= minimum <= maximum <= body
        and minimum * chunks <= body <= maximum * chunks
    )


def _histogram(value: object) -> dict[int, int] | None:
    bins = object_list(value)
    if not isinstance(value, list) or not bins or len(bins) != len(value):
        return None
    result = {}
    for item in bins:
        size, count = item.get("size_bytes"), item.get("count")
        if type(size) is not int or type(count) is not int or size <= 0 or count <= 0 or size in result:
            return None
        result[size] = count
    return result


def _replay_matches(replay: JsonObject, histogram: dict[int, int], config: JsonObject) -> bool:
    segments = object_list(replay.get("segments"))
    if not segments or len(segments) > MAX_REPLAY_SEGMENTS:
        return False
    combined: dict[int, int] = {}
    for segment in segments:
        bins = _histogram(segment.get("histogram"))
        if bins is None:
            return False
        size = sum(size * count for size, count in bins.items())
        chunks = sum(bins.values())
        if (
            segment.get("replay_bytes") != size
            or segment.get("replay_chunks") != chunks
            or size > int_value(config.get("replay_max_bytes"))
            or chunks > int_value(config.get("replay_max_chunks"))
        ):
            return False
        for key in ("scalar_only_s", "sha256_only_s", "combined_s"):
            duration = number(segment.get(key))
            if duration is None or duration < 0:
                return False
        for size, count in bins.items():
            combined[size] = combined.get(size, 0) + count
    if combined != histogram:
        return False
    return (
        replay.get("replay_bytes") == sum(size * count for size, count in histogram.items())
        and replay.get("replay_chunks") == sum(histogram.values())
        and all(
            (total := number(replay.get(key))) is not None
            and math.isclose(
                total,
                sum(number(segment.get(key)) or 0.0 for segment in segments),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for key in ("scalar_only_s", "sha256_only_s", "combined_s")
        )
    )
