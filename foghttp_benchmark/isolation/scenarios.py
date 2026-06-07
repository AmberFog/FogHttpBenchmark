__all__ = ("scenario_names_for_isolation",)

from foghttp_benchmark.constants import (
    CLIENT_CREATION_SUITE,
    COMPRESSED_RESPONSE_SUITE,
    DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
    DEFAULT_ONE_UPSTREAM_SCENARIOS,
    DEFAULT_PROXY_CONNECT_SCENARIOS,
    DEFAULT_REQUEST_BUILDER_SCENARIOS,
    DEFAULT_RESOURCE_SCENARIOS,
    DEFAULT_SCENARIOS,
    DEFAULT_STREAMING_SCENARIOS,
    ONE_UPSTREAM_SUITE,
    PROXY_CONNECT_SUITE,
    REQUEST_BUILDER_SUITE,
    RESOURCE_BACKPRESSURE_SUITE,
    RESPONSE_STREAMING_SUITE,
)
from foghttp_benchmark.models import BenchmarkArgs


def scenario_names_for_isolation(args: BenchmarkArgs) -> list[str]:
    if args.suite == CLIENT_CREATION_SUITE:
        return []
    if args.scenarios != DEFAULT_SCENARIOS:
        return parse_csv(args.scenarios)
    return parse_csv(default_scenarios(args.suite))


def default_scenarios(suite: str) -> str:
    defaults = {
        COMPRESSED_RESPONSE_SUITE: DEFAULT_COMPRESSED_RESPONSE_SCENARIOS,
        ONE_UPSTREAM_SUITE: DEFAULT_ONE_UPSTREAM_SCENARIOS,
        PROXY_CONNECT_SUITE: DEFAULT_PROXY_CONNECT_SCENARIOS,
        REQUEST_BUILDER_SUITE: DEFAULT_REQUEST_BUILDER_SCENARIOS,
        RESOURCE_BACKPRESSURE_SUITE: DEFAULT_RESOURCE_SCENARIOS,
        RESPONSE_STREAMING_SUITE: DEFAULT_STREAMING_SCENARIOS,
    }
    return defaults.get(suite, DEFAULT_SCENARIOS)


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
