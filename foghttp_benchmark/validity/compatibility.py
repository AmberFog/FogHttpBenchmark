__all__ = (
    "compatibility_expected_error_count",
    "compatibility_failure_reasons",
)

from dataclasses import dataclass
from typing import Literal, TypeAlias

from foghttp_benchmark.constants import COMPRESSED_RESPONSE_SUITE, REQUESTS_SUITE, RESPONSE_STREAMING_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import dict_field, int_field, row_reference, str_field, validity_reason
from foghttp_benchmark.validity.models import ValidityReason


ErrorField: TypeAlias = Literal["error_types", "warmup_error_types"]


@dataclass(frozen=True, slots=True)
class CompatibilityFailure:
    suite: str
    client: str
    cases: frozenset[str]
    error_types: frozenset[str]
    message: str
    modes: frozenset[str] | None = None
    case_field: str = "scenario"
    error_fields: frozenset[ErrorField] = frozenset(("error_types", "warmup_error_types"))

    def matches(self, suite: str, row: JsonObject, error_field: ErrorField) -> bool:
        if self.suite != suite or error_field not in self.error_fields:
            return False
        if str_field(row, "client") != self.client:
            return False
        if self.modes is not None and str_field(row, "mode") not in self.modes:
            return False
        return str_field(row, self.case_field) in self.cases


EXPECTED_COMPATIBILITY_FAILURES: tuple[CompatibilityFailure, ...] = (
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="aiohttp",
        cases=frozenset(("multi-gzip-deflate-64k",)),
        error_types=frozenset(("check_failed",)),
        message="aiohttp decodes the multi-encoding response differently from this suite contract.",
    ),
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="zapros",
        cases=frozenset(("br-64k",)),
        error_types=frozenset(("ConnectionError", "ImportError")),
        message="zapros std handler has known brotli compatibility failures in this benchmark case.",
    ),
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="zapros",
        cases=frozenset(("multi-gzip-deflate-64k",)),
        error_types=frozenset(("ConnectionError", "DecodingError")),
        message="zapros std handler has known multi-encoding compatibility failures in this benchmark case.",
    ),
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="zapros-pyreqwest",
        cases=frozenset(("br-64k",)),
        error_types=frozenset(("ImportError",)),
        message="zapros[pyreqwest] has known brotli compatibility failures in this benchmark case.",
    ),
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="zapros-pyreqwest",
        cases=frozenset(("multi-gzip-deflate-64k",)),
        error_types=frozenset(("DecodingError",)),
        message="zapros[pyreqwest] has known multi-encoding compatibility failures in this benchmark case.",
    ),
    CompatibilityFailure(
        suite=COMPRESSED_RESPONSE_SUITE,
        client="zapros-pyreqwest",
        cases=frozenset(("gzip-json-small", "gzip-64k", "deflate-64k", "gzip-high-ratio-1m")),
        error_types=frozenset(("RuntimeError",)),
        message="zapros[pyreqwest] sync warmup intermittently reports RuntimeError in compressed cases.",
        modes=frozenset(("sync",)),
        error_fields=frozenset(("warmup_error_types",)),
    ),
    CompatibilityFailure(
        suite=RESPONSE_STREAMING_SUITE,
        client="aiohttp",
        cases=frozenset(("long-line-1m",)),
        error_types=frozenset(("LineTooLong",)),
        message="aiohttp line reader rejects this intentionally long-line streaming case.",
        modes=frozenset(("async",)),
        case_field="case",
    ),
    CompatibilityFailure(
        suite=REQUESTS_SUITE,
        client="zapros-pyreqwest",
        cases=frozenset(
            (
                "json-small",
                "json-decode-small",
                "bytes-64k",
                "post-json-echo",
                "post-echo-64k",
                "redirect-get-302",
                "redirect-head-302",
                "redirect-post-303",
                "redirect-post-307",
                "delay-20ms",
                "pool-contention-20ms",
            ),
        ),
        error_types=frozenset(("RuntimeError",)),
        message="zapros[pyreqwest] sync warmup intermittently reports RuntimeError in request cases.",
        modes=frozenset(("sync",)),
        error_fields=frozenset(("warmup_error_types",)),
    ),
)


def compatibility_expected_error_count(suite: str, row: JsonObject, error_field: ErrorField) -> int:
    error_types = dict_field(row, error_field)
    total_field = "errors_total" if error_field == "error_types" else "warmup_errors_total"
    if any(count < 0 for count in error_types.values()) or sum(error_types.values()) != int_field(row, total_field):
        return 0
    expected_types = compatibility_error_types(suite, row, error_field)
    return sum(count for name, count in error_types.items() if name in expected_types)


def compatibility_failure_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    messages = {
        failure.message
        for failure in EXPECTED_COMPATIBILITY_FAILURES
        for error_field in failure.error_fields
        if failure.matches(suite, row, error_field)
        and any(count > 0 and name in failure.error_types for name, count in dict_field(row, error_field).items())
    }
    if not messages:
        return []
    return [
        validity_reason(
            status="warning",
            code="expected_compatibility_failure",
            message=(
                " ".join(sorted(messages)) + " Affected rows are diagnostic only; performance comparison is blocked."
            ),
            row=row_reference(row),
        ),
    ]


def compatibility_error_types(suite: str, row: JsonObject, error_field: ErrorField) -> frozenset[str]:
    expected_types: set[str] = set()
    for failure in EXPECTED_COMPATIBILITY_FAILURES:
        if failure.matches(suite, row, error_field):
            expected_types.update(failure.error_types)
    return frozenset(expected_types)
