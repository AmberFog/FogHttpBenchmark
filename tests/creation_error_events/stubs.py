from foghttp_benchmark.clients.base import AsyncClientAdapter, SyncClientAdapter
from foghttp_benchmark.models import ResponseOutcome, Scenario
from foghttp_benchmark.resources import ResourceSnapshot
from tests.creation_error_events.cases import CreationFailureCase


def request_outcome(case: CreationFailureCase) -> ResponseOutcome:
    if case.request_failure:
        msg = "offline request failure"
        raise RuntimeError(msg)
    return ResponseOutcome(status_code=500 if case.failed_check else 200)


class FailingSyncClient(SyncClientAdapter):
    def __init__(self, case: CreationFailureCase) -> None:
        self.case = case

    def request(self, _scenario: Scenario, _url: str) -> ResponseOutcome:
        return request_outcome(self.case)

    def close(self) -> None:
        msg = "offline close failure"
        raise ValueError(msg)


class FailingAsyncClient(AsyncClientAdapter):
    def __init__(self, case: CreationFailureCase) -> None:
        self.case = case

    async def request(self, _scenario: Scenario, _url: str) -> ResponseOutcome:
        return request_outcome(self.case)

    async def close(self) -> None:
        msg = "offline close failure"
        raise ValueError(msg)


def snapshot_failure() -> ResourceSnapshot:
    msg = "offline snapshot failure"
    raise OSError(msg)
