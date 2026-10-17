__all__ = (
    "LifecycleCase",
    "LifecycleConfig",
    "build_lifecycle_plan",
    "lifecycle_config_from_payload",
    "validate_lifecycle_case",
    "validate_lifecycle_config",
)

from dataclasses import asdict, dataclass
import math
import random
from typing import Any

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.streaming.attribution_models import AttributionConfig, validate_attribution_config


MAX_REPEATS = 3
MAX_CASES = 48
MIN_NATIVE_PROFILE_DURATION_S = 2
MIN_PERF_PROFILE_DURATION_S = 1


@dataclass(frozen=True, slots=True)
class LifecycleConfig:
    body_bytes: int = 1_048_576
    server_write_bytes: int = 65_536
    warmup_rounds: int = 2
    batches: int = 5
    rounds_per_batch: int = 20
    sample_interval_s: float = 0.05
    case_timeout_s: float = 240.0
    settle_timeout_s: float = 5.0
    rss_ceiling_bytes: int = 2 * 1024 * 1024 * 1024
    max_samples: int = 12_000
    post_gc: bool = True
    attribution: AttributionConfig | None = None


@dataclass(frozen=True, slots=True)
class LifecycleCase:
    sequence: int
    client: str
    mode: str
    case: str
    concurrency: int
    repeat: int


BASELINE_CONFIG = LifecycleConfig()


def _validate_config_types(config: LifecycleConfig) -> None:
    values = asdict(config)
    for name in (
        "body_bytes",
        "server_write_bytes",
        "warmup_rounds",
        "batches",
        "rounds_per_batch",
        "rss_ceiling_bytes",
        "max_samples",
    ):
        if type(values[name]) is not int:
            msg = f"Lifecycle {name} must be an integer"
            raise ValueError(msg)
    for name in ("sample_interval_s", "case_timeout_s", "settle_timeout_s"):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            msg = f"Lifecycle {name} must be a finite number"
            raise ValueError(msg)
    if type(values["post_gc"]) is not bool:
        msg = "Lifecycle post_gc must be boolean"
        raise ValueError(msg)


def validate_lifecycle_config(config: LifecycleConfig) -> None:
    _validate_config_types(config)
    if not 0 < config.server_write_bytes < config.body_bytes <= BASELINE_CONFIG.body_bytes:
        msg = "Lifecycle bodies must fit 1 MiB with a smaller server fragment"
        raise ValueError(msg)
    if (
        not 0 <= config.warmup_rounds <= BASELINE_CONFIG.warmup_rounds
        or not 1 <= config.batches <= BASELINE_CONFIG.batches
        or not 1 <= config.rounds_per_batch <= BASELINE_CONFIG.rounds_per_batch
    ):
        msg = "Lifecycle request cap: warmup <= 2 rounds, batches <= 5, rounds per batch <= 20"
        raise ValueError(msg)
    if not 0 < config.sample_interval_s <= 1 or not 0 < config.settle_timeout_s <= BASELINE_CONFIG.settle_timeout_s:
        msg = "Lifecycle sampling and settlement intervals must be positive and bounded"
        raise ValueError(msg)
    if (
        not 0 < config.case_timeout_s <= BASELINE_CONFIG.case_timeout_s
        or not 0 < config.rss_ceiling_bytes <= BASELINE_CONFIG.rss_ceiling_bytes
    ):
        msg = "Lifecycle limits must fit a 240-second deadline and 2 GiB per PID"
        raise ValueError(msg)
    if not 1 <= config.max_samples <= BASELINE_CONFIG.max_samples:
        msg = "Lifecycle resource samples must be bounded by 12000 scalar records"
        raise ValueError(msg)
    if config.attribution is not None:
        validate_attribution_config(config.attribution)
        _validate_profile_window(config)
        if config.attribution.minimum_duration_s and (
            config.batches != 1
            or config.attribution.minimum_duration_s + config.settle_timeout_s >= config.case_timeout_s
        ):
            msg = "Duration windows require one batch and room for settlement inside the existing case deadline"
            raise ValueError(msg)
        writes = math.ceil(config.body_bytes / config.server_write_bytes)
        rounds = config.warmup_rounds + config.batches * config.rounds_per_batch
        if (writes - 1) * config.attribution.server_delay_s * rounds >= config.case_timeout_s:
            msg = "Configured server delays alone exceed the hard per-case deadline"
            raise ValueError(msg)


def _validate_profile_window(config: LifecycleConfig) -> None:
    attribution = config.attribution
    if attribution is None:
        return
    if attribution.profiler.startswith("sample-"):
        minimum, name = MIN_NATIVE_PROFILE_DURATION_S, "Native sampling"
    elif attribution.profiler.startswith("perf-"):
        minimum, name = MIN_PERF_PROFILE_DURATION_S, "Linux perf sampling"
    else:
        return
    if config.batches != 1 or attribution.minimum_duration_s < minimum:
        msg = f"{name} requires one duration window of at least {minimum} second(s)"
        raise ValueError(msg)


def lifecycle_config_from_payload(payload: JsonObject) -> LifecycleConfig:
    values: dict[str, Any] = dict(payload)
    attribution = values.pop("attribution", None)
    if attribution is not None and not isinstance(attribution, dict):
        msg = "Attribution configuration must be an object"
        raise TypeError(msg)
    return LifecycleConfig(
        **values,
        attribution=AttributionConfig(**attribution) if attribution is not None else None,
    )


def build_lifecycle_plan(
    *,
    clients: list[str],
    modes: list[str],
    cases: list[str],
    concurrency_levels: list[int],
    repeats: int,
    seed: int,
    shuffle: bool,
) -> list[LifecycleCase]:
    validate_selection(clients, modes, cases, concurrency_levels, repeats)
    plan = [
        LifecycleCase(0, client, mode, case, concurrency, repeat)
        for client in dict.fromkeys(clients)
        for mode in dict.fromkeys(modes)
        for case in dict.fromkeys(cases)
        for concurrency in dict.fromkeys(concurrency_levels)
        for repeat in range(1, repeats + 1)
    ]
    if shuffle:
        random.Random(seed).shuffle(plan)  # noqa: S311 - reproducible case ordering, not security.
    return [
        LifecycleCase(index, item.client, item.mode, item.case, item.concurrency, item.repeat)
        for index, item in enumerate(plan, start=1)
    ]


def validate_lifecycle_case(case: LifecycleCase, config: LifecycleConfig | None = None) -> None:
    if type(case.sequence) is not int or not 1 <= case.sequence <= MAX_CASES:
        msg = "Lifecycle case sequence must be a positive integer within the bounded plan"
        raise ValueError(msg)
    if type(case.concurrency) is not int or type(case.repeat) is not int:
        msg = "Lifecycle concurrency and repetition must be integers"
        raise ValueError(msg)
    validate_selection([case.client], [case.mode], [case.case], [case.concurrency], case.repeat)
    if config is not None and config.attribution is not None:
        if case.mode != "async" or case.case != "stream-1m":
            msg = "Async bytes measurements require async stream-1m; early close and cancellation are controls"
            raise ValueError(msg)
        validate_attribution_config(config.attribution, client=case.client)
        if (
            config.attribution.minimum_duration_s
            and config.attribution.max_window_streams < config.rounds_per_batch * case.concurrency
        ):
            msg = "Window stream limit must accommodate all declared minimum rounds"
            raise ValueError(msg)


def validate_selection(
    clients: list[str],
    modes: list[str],
    cases: list[str],
    concurrency_levels: list[int],
    repeats: int,
) -> None:
    if not clients or not set(clients) <= {"foghttp", "httpx"}:
        msg = "Lifecycle profile supports foghttp and httpx"
        raise ValueError(msg)
    if not modes or not set(modes) <= {"sync", "async"}:
        msg = "Lifecycle profile requires sync or async modes"
        raise ValueError(msg)
    if not cases or not set(cases) <= {"first-chunk-close-1m", "stream-1m"}:
        msg = "Lifecycle profile supports first-chunk-close-1m and stream-1m"
        raise ValueError(msg)
    if not concurrency_levels or not set(concurrency_levels) <= {1, 10} or not 1 <= repeats <= MAX_REPEATS:
        msg = "Lifecycle profile requires concurrency 1/10 and at most 3 fresh repetitions"
        raise ValueError(msg)
