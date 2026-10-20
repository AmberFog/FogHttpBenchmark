import pytest

from tests.resource_metrics.cases import RESOURCE_REPORT_CASES, ResourceReportCase


@pytest.fixture(params=RESOURCE_REPORT_CASES, ids=lambda case: case.suite)
def resource_case(request: pytest.FixtureRequest) -> ResourceReportCase:
    return request.param
