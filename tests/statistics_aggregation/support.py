from dataclasses import dataclass

from foghttp_benchmark.resource_metrics import ResourceMetricCoverage


@dataclass(frozen=True, slots=True)
class Observation:
    repeat: int
    rate: float
    errors: int
    error_types: dict[str, int]
    warmup_errors: int
    warmup_error_types: dict[str, int]
    rss_mb: float | None


OBSERVATIONS = (
    Observation(1, 10.0, 1, {"TimeoutError": 1, "ZeroCount": 0}, 0, {}, None),
    Observation(2, 20.0, 2, {"TimeoutError": 2}, 1, {"WarmupError": 1}, 0.0),
    Observation(3, 30.0, 3, {"ProtocolError": 3}, 2, {"WarmupError": 2}, 8.0),
)
EXPECTED_RATE = 20.0
EXPECTED_CV_PERCENT = 50.0
EXPECTED_ERROR_TOTAL = 6
EXPECTED_WARMUP_ERROR_TOTAL = 3
EXPECTED_ERROR_TYPES = {"TimeoutError": 3, "ZeroCount": 0, "ProtocolError": 3}
EXPECTED_WARMUP_ERROR_TYPES = {"WarmupError": 3}
EXPECTED_RSS_MB = 8.0
EXPECTED_PARTIAL_COVERAGE = ResourceMetricCoverage(2, 3, ("reason-not-recorded",))
EXPECTED_UNAVAILABLE_COVERAGE = ResourceMetricCoverage(0, 3, ("reason-not-recorded",))
EXPECTED_COMPLETE_COVERAGE = ResourceMetricCoverage(3, 3)
