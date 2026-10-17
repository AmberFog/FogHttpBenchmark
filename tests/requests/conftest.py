import pytest

from foghttp_benchmark.models import RunResult
from tests.requests.factories import run_result


@pytest.fixture
def error_results() -> list[RunResult]:
    return [
        run_result(
            repeat=0,
            errors=3,
            warmup_errors=1,
            error_types={"RequestError": 2, "check_failed": 1},
            warmup_error_types={"RequestError": 1},
        ),
        run_result(
            repeat=1,
            errors=4,
            warmup_errors=2,
            error_types={"RequestError": 3, "TimeoutError": 1},
            warmup_error_types={"TimeoutError": 2},
        ),
    ]
