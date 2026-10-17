from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from foghttp_benchmark.models import BenchmarkArgs, JsonObject
from foghttp_benchmark.streaming.attribution_models import AttributionConfig
from foghttp_benchmark.streaming.attribution_reports import write_attribution_reports
from foghttp_benchmark.streaming.lifecycle_models import LifecycleCase, LifecycleConfig
from tests.streaming.attribution_report_factory import BODY_BYTES, config, provenance, result


STREAMS_PER_REPLAY_SEGMENT = 10
CHUNKS_PER_STREAM = 2
CHUNK_BYTES = BODY_BYTES // CHUNKS_PER_STREAM


def window_config(*, stream_limit: int = 40) -> LifecycleConfig:
    return replace(
        config(),
        attribution=replace(
            AttributionConfig(),
            minimum_duration_s=1.0,
            max_window_streams=stream_limit,
            replay_max_bytes=BODY_BYTES * STREAMS_PER_REPLAY_SEGMENT,
            replay_max_chunks=CHUNKS_PER_STREAM * STREAMS_PER_REPLAY_SEGMENT,
        ),
    )


def window_result(
    repeat: int,
    configuration: LifecycleConfig,
    *,
    streams: int = 30,
    duration: float = 1.0,
) -> JsonObject:
    value = result(repeat, duration=duration)
    child = value["client_report"]
    child["config"] = asdict(configuration)
    batch = child["batches"][0]
    template = batch["samples"][0]
    samples = []
    for stream in range(1, streams + 1):
        sample = deepcopy(template)
        sample.update(stream=stream, duration_ms=duration * 1000 / streams)
        sample["distribution"].update(scope="batch-global", histogram=[])
        samples.append(sample)
    batch.update(
        rounds=streams,
        requests=streams,
        ok_streams=streams,
        verified_success_bytes=BODY_BYTES * streams,
        total_observed_bytes=BODY_BYTES * streams,
        bytes_read_total=BODY_BYTES * streams,
        chunks_read_total=CHUNKS_PER_STREAM * streams,
        samples=samples,
        window={
            "minimum_duration_s": 1.0,
            "minimum_rounds": configuration.rounds_per_batch,
            "max_streams": configuration.attribution.max_window_streams,
            "stop_reason": "duration-reached" if duration >= 1.0 else "stream-limit",
            "target_reached": duration >= 1.0,
            "global_histogram": {
                "histogram": [{"size_bytes": CHUNK_BYTES, "count": CHUNKS_PER_STREAM * streams}],
                "complete": True,
                "observed_count": CHUNKS_PER_STREAM * streams,
                "observed_bytes": BODY_BYTES * streams,
                "bins_cap": configuration.attribution.histogram_bins_cap,
                "scope": "batch-global",
            },
        },
    )
    segments = []
    for offset in range(0, streams, STREAMS_PER_REPLAY_SEGMENT):
        count = min(STREAMS_PER_REPLAY_SEGMENT, streams - offset)
        segments.append(
            {
                "histogram": [{"size_bytes": CHUNK_BYTES, "count": CHUNKS_PER_STREAM * count}],
                "replay_bytes": BODY_BYTES * count,
                "replay_chunks": CHUNKS_PER_STREAM * count,
                "scalar_only_s": 0.01,
                "sha256_only_s": 0.02,
                "combined_s": 0.03,
            },
        )
    batch["overhead"].update(
        segments=segments,
        replay_bytes=BODY_BYTES * streams,
        replay_chunks=CHUNKS_PER_STREAM * streams,
        **{key: sum(segment[key] for segment in segments) for key in ("scalar_only_s", "sha256_only_s", "combined_s")},
    )
    return value


def write_window_report(
    directory: Path,
    values: list[JsonObject] | None = None,
    configuration: LifecycleConfig | None = None,
) -> Path:
    selected_config = configuration if configuration is not None else window_config()
    results = values if values is not None else [window_result(repeat, selected_config) for repeat in range(1, 4)]
    arguments = BenchmarkArgs(
        suite="response-streaming",
        clients="foghttp",
        modes="async",
        concurrency="1",
        requests=selected_config.rounds_per_batch,
        warmup=0,
        repeats=len(results),
        max_redirects=5,
        seed=42,
        no_shuffle=True,
        output_dir=str(directory),
        scenarios="stream-1m",
        iterations=1,
        client_counts="1",
    )
    with patch("foghttp_benchmark.validity.reports.research_provenance_from_env", return_value=provenance()):
        write_attribution_reports(
            results,
            arguments,
            selected_config,
            [LifecycleCase(**item["case"]) for item in results],
        )
    return directory / "latest.json"
