import pytest

from tests.resource_metrics.cases import (
    OBSERVATION_CASES,
    OBSERVATION_IDS,
    RESOURCE_REPORT_CASES,
    ResourceReportCase,
)


@pytest.fixture(params=RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def resource_case(request: pytest.FixtureRequest) -> ResourceReportCase:
    return request.param


@pytest.fixture(params=OBSERVATION_CASES, ids=OBSERVATION_IDS)
def observations(request: pytest.FixtureRequest) -> tuple[int | None, ...]:
    return request.param
