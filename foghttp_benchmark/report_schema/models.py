__all__ = ("REPORT_SCHEMA_VERSION", "REPORT_SUITES", "DecodedReport")

from dataclasses import dataclass

from foghttp_benchmark.models import JsonObject


REPORT_SCHEMA_VERSION = 1
REPORT_SUITES = (
    "requests",
    "client-creation",
    "resource-backpressure",
    "one-upstream",
    "request-builder",
    "compressed-response",
    "response-streaming",
    "proxy-connect",
)


@dataclass(frozen=True, slots=True)
class DecodedReport:
    suite: str
    metadata: JsonObject
    aggregate_rows: list[JsonObject]
    run_rows: list[JsonObject]
