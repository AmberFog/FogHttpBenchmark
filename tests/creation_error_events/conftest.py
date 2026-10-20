import pytest

from foghttp_benchmark.models import ClientCreationResult
from tests.creation_error_events.actions import run_failure_case
from tests.creation_error_events.cases import FAILURE_CASES, REQUEST_CLOSE_FAILURE, CreationFailureCase


@pytest.fixture(params=FAILURE_CASES, ids=lambda case: f"{case.scenario}-{','.join(case.expected_error_types)}")
def failure_case(request: pytest.FixtureRequest) -> CreationFailureCase:
    return request.param


@pytest.fixture(params=("async", "sync"))
def creation_result(
    request: pytest.FixtureRequest,
    failure_case: CreationFailureCase,
    monkeypatch: pytest.MonkeyPatch,
) -> ClientCreationResult:
    return run_failure_case(failure_case, request.param, monkeypatch)


@pytest.fixture(params=("async", "sync"))
def request_close_result(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> ClientCreationResult:
    return run_failure_case(REQUEST_CLOSE_FAILURE, request.param, monkeypatch)
