__all__ = ("resource_coverage_field", "validate_ordinary_resource_coverage", "validate_resource_coverage")

from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.report_schema.fields import require_integer, require_object, require_string
from foghttp_benchmark.report_schema.identity import aggregate_identity
from foghttp_benchmark.resource_metrics import ResourceCoverage, ResourceMetricCoverage


RAW_RESOURCE_FIELDS = {
    "rss_mb_max": "peak_rss_mb",
    "threads_max": "peak_threads",
    "fds_max": "peak_fds",
    "peak_active_requests_max": "peak_active_requests",
    "peak_pending_requests_max": "peak_pending_requests",
    "peak_buffered_response_bytes_max": "peak_buffered_response_bytes",
    **{
        f"{phase}_{metric}_delta{unit}_max": f"{phase}_{metric}_delta{unit}"
        for phase in ("peak", "end")
        for metric, unit in (("rss", "_mb"), ("threads", ""), ("fds", ""))
    },
}
CLIENT_STAT_FIELDS = {
    f"final_{key}_max": key
    for key in (
        "failed_requests",
        "buffered_response_bytes",
        "buffered_response_budget_rejections",
        "active_requests",
        "response_body_closed",
        "response_body_reuse_eligible",
        "response_body_aborted",
        "connections_opened",
        "connections_reused",
        "connections_closed",
        "connections_aborted",
        "idle_connections",
    )
} | {"final_pool_timeouts_max": "pool_acquire_timeouts"}


def resource_coverage_field(row: JsonObject, path: str = "row") -> ResourceCoverage:
    if "resource_coverage" not in row:
        return {}
    value = require_object(row["resource_coverage"], f"{path}.resource_coverage")
    coverage: ResourceCoverage = {}
    for metric, observation in value.items():
        require_string(metric, f"{path}.resource_coverage metric")
        field_path = f"{path}.resource_coverage.{metric}"
        record = require_object(observation, field_path)
        available = require_integer(record.get("available"), f"{field_path}.available")
        expected = require_integer(record.get("expected"), f"{field_path}.expected")
        if available > expected:
            msg = f"{field_path} requires 0 <= available <= expected"
            raise ValueError(msg)
        reasons = record.get("unavailable_reasons")
        if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
            msg = f"{field_path}.unavailable_reasons must be a list of strings"
            raise ValueError(msg)
        coverage[metric] = ResourceMetricCoverage(available, expected, tuple(reasons))
    return coverage


def validate_resource_coverage(row: JsonObject, path: str, *, current: bool) -> ResourceCoverage:
    if current and "resource_coverage" not in row:
        msg = f"{path}.resource_coverage is required by resource_metric_schema_version=2"
        raise ValueError(msg)
    coverage = resource_coverage_field(row, path)
    for metric, observation in coverage.items():
        if metric not in row:
            msg = f"{path}.{metric} is required by its resource_coverage observation"
            raise ValueError(msg)
        if (row[metric] is None) != (observation.available == 0):
            msg = f"{path}.{metric} disagrees with resource_coverage.available"
            raise ValueError(msg)
    return coverage


def validate_ordinary_resource_coverage(
    suite: str,
    aggregates: list[JsonObject],
    runs: list[JsonObject],
    *,
    current: bool,
) -> None:
    run_groups: dict[tuple[str, ...], list[JsonObject]] = {}
    for run in runs:
        run_groups.setdefault(aggregate_identity(suite, run), []).append(run)
    for index, row in enumerate(aggregates):
        path = f"aggregate[{index}]"
        coverage = validate_resource_coverage(row, path, current=current)
        if not coverage:
            continue
        repeats = require_integer(row.get("repeats"), f"{path}.repeats", minimum=1)
        for metric, observation in coverage.items():
            if observation.expected != repeats:
                msg = f"{path}.resource_coverage.{metric}.expected must match repeats ({repeats})"
                raise ValueError(msg)
        if runs:
            observations = run_groups.get(aggregate_identity(suite, row), [])
            if len(observations) != repeats:
                msg = f"{path}.resource_coverage requires {repeats} matching run records, got {len(observations)}"
                raise ValueError(msg)
            validate_resource_observations(coverage, observations, path)


def validate_resource_observations(coverage: ResourceCoverage, runs: list[JsonObject], path: str) -> None:
    for metric, observation in coverage.items():
        if metric in RAW_RESOURCE_FIELDS:
            available = sum(run.get(RAW_RESOURCE_FIELDS[metric]) is not None for run in runs)
        elif metric in CLIENT_STAT_FIELDS:
            available = sum(
                run.get("client_stats") is not None
                and require_object(run["client_stats"], "run.client_stats").get(CLIENT_STAT_FIELDS[metric]) is not None
                for run in runs
            )
        else:
            continue
        if observation.available != available:
            msg = f"{path}.resource_coverage.{metric}.available must match recorded observations ({available})"
            raise ValueError(msg)
