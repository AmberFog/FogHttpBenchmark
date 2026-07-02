__all__ = ("has_proxy_bypass_errors", "proxy_specific_reasons")

from foghttp_benchmark.constants import PROXY_CONNECT_SUITE
from foghttp_benchmark.models import JsonObject
from foghttp_benchmark.validity.helpers import dict_field, int_field, row_reference, str_field, validity_reason
from foghttp_benchmark.validity.models import ValidityReason


PROXY_BYPASS_ERROR_TYPES = frozenset(("proxy_http_bypass", "proxy_connect_bypass"))


def proxy_specific_reasons(suite: str, row: JsonObject) -> list[ValidityReason]:
    if suite != PROXY_CONNECT_SUITE:
        return []
    reasons: list[ValidityReason] = []
    error_types = dict_field(row, "error_types")
    bypass_errors = sorted(PROXY_BYPASS_ERROR_TYPES & set(error_types))
    if bypass_errors:
        reasons.append(
            validity_reason(
                status="invalid",
                code="proxy_usage_guard_failed",
                message=f"Proxy usage guard errors were recorded: {', '.join(bypass_errors)}.",
                row=row_reference(row),
            ),
        )

    config = str_field(row, "config")
    target_scheme = str_field(row, "target_scheme")
    ok_requests = int_field(row, "ok_requests_total")
    measured_http = int_field(row, "measured_proxy_http_requests_max")
    measured_connect = int_field(row, "measured_proxy_connect_requests_max")
    total_http = int_field(row, "total_proxy_http_requests_max")
    total_connect = int_field(row, "total_proxy_connect_requests_max")

    if config == "direct" and any(value > 0 for value in (measured_http, measured_connect, total_http, total_connect)):
        reasons.append(
            validity_reason(
                status="invalid",
                code="direct_proxy_counter_leak",
                message="Direct proxy baseline recorded proxy counters.",
                row=row_reference(row),
            ),
        )
    if config in ("explicit", "trust-env") and ok_requests > 0:
        reasons.extend(
            missing_proxy_counter_reasons(
                row,
                target_scheme,
                measured_http,
                measured_connect,
                total_connect,
            ),
        )
    return reasons


def missing_proxy_counter_reasons(
    row: JsonObject,
    target_scheme: str,
    measured_http: int,
    measured_connect: int,
    total_connect: int,
) -> list[ValidityReason]:
    if target_scheme == "http" and measured_http <= 0:
        return [
            validity_reason(
                status="invalid",
                code="missing_proxy_http_counter",
                message="HTTP proxy scenario completed successful requests without measured proxy HTTP counters.",
                row=row_reference(row),
            ),
        ]
    if target_scheme == "https" and connect_counter_value(row, measured_connect, total_connect) <= 0:
        return [
            validity_reason(
                status="invalid",
                code="missing_proxy_connect_counter",
                message="HTTPS proxy scenario completed successful requests without measured CONNECT counters.",
                row=row_reference(row),
            ),
        ]
    return []


def connect_counter_value(row: JsonObject, measured_connect: int, total_connect: int) -> int:
    if str_field(row, "lifecycle") == "cold-client":
        return measured_connect
    return total_connect


def has_proxy_bypass_errors(row: JsonObject) -> bool:
    error_types = dict_field(row, "error_types")
    return bool(PROXY_BYPASS_ERROR_TYPES & set(error_types))
