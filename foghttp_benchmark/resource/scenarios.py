__all__ = ("ResourceCase", "resource_cases")

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceCase:
    name: str
    path: str
    request_limit: int
    max_pending_requests: int | None
    per_origin_request_limit: int | None = None
    max_response_body_size: int | None = None
    max_buffered_response_bytes: int | None = None
    pool_timeout_s: float = 5.0
    total_timeout_s: float = 30.0
    expected_content_length: int | None = None
    expected_json_keys: tuple[str, ...] = ()
    secondary_path: str | None = None
    recovery_path: str | None = "/json-small"
    description: str = ""


def resource_cases() -> dict[str, ResourceCase]:
    return {
        "active-limit-serial": ResourceCase(
            name="active-limit-serial",
            path="/delay/20",
            request_limit=1,
            max_pending_requests=None,
            per_origin_request_limit=1,
            expected_json_keys=("ok", "message", "items"),
            description="One active request slot, many waiters, no expected errors.",
        ),
        "pool-timeout-recovery": ResourceCase(
            name="pool-timeout-recovery",
            path="/delay/20",
            request_limit=1,
            max_pending_requests=None,
            per_origin_request_limit=1,
            pool_timeout_s=0.005,
            total_timeout_s=2.0,
            expected_json_keys=("ok", "message", "items"),
            description="Short pool timeout under contention followed by a health-check request.",
        ),
        "pending-queue-full": ResourceCase(
            name="pending-queue-full",
            path="/json-small",
            request_limit=0,
            max_pending_requests=0,
            pool_timeout_s=0.005,
            recovery_path=None,
            description="No active slots and no pending queue; requests should fail as PoolTimeout.",
        ),
        "per-origin-isolation": ResourceCase(
            name="per-origin-isolation",
            path="/delay/20",
            secondary_path="/delay/20",
            request_limit=2,
            max_pending_requests=None,
            per_origin_request_limit=1,
            expected_json_keys=("ok", "message", "items"),
            description="Two origins, one active slot per origin, and two global active slots.",
        ),
        "response-body-limit": ResourceCase(
            name="response-body-limit",
            path="/bytes/131072",
            request_limit=1,
            max_pending_requests=None,
            per_origin_request_limit=1,
            max_response_body_size=65536,
            pool_timeout_s=5.0,
            expected_content_length=131072,
            recovery_path="/bytes/1024",
            description="Buffered response body exceeds max_response_body_size and must release slots.",
        ),
        "aggregate-buffered-budget": ResourceCase(
            name="aggregate-buffered-budget",
            path="/drip-bytes/65536/4096/2",
            request_limit=10,
            max_pending_requests=None,
            per_origin_request_limit=10,
            max_response_body_size=131072,
            max_buffered_response_bytes=98304,
            pool_timeout_s=5.0,
            total_timeout_s=5.0,
            expected_content_length=65536,
            recovery_path="/bytes/1024",
            description=(
                "Concurrent buffered responses fit per-response limit but exceed aggregate buffered byte budget."
            ),
        ),
    }
