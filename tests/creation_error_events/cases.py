from dataclasses import dataclass


@dataclass(frozen=True)
class CreationFailureCase:
    scenario: str
    expected_error_types: dict[str, int]
    iterations: int = 2
    client_count: int = 2
    request_failure: bool = False
    failed_check: bool = False
    snapshot_failure: bool = False


REQUEST_CLOSE_FAILURE = CreationFailureCase(
    "create-first-request",
    {"RuntimeError": 2, "close_ValueError": 2},
    request_failure=True,
)

FAILURE_CASES = (
    CreationFailureCase("create-close", {"ValueError": 2}),
    REQUEST_CLOSE_FAILURE,
    CreationFailureCase(
        "create-first-request",
        {"check_failed": 2, "OSError": 2, "close_ValueError": 2},
        failed_check=True,
        snapshot_failure=True,
    ),
    CreationFailureCase(
        "reused-request",
        {"check_failed": 2, "OSError": 1, "close_ValueError": 1},
        failed_check=True,
        snapshot_failure=True,
    ),
    CreationFailureCase(
        "many-clients-open-close",
        {"OSError": 1, "close_ValueError": 2},
        snapshot_failure=True,
    ),
)
