__all__ = ("AsyncClientAdapter", "SyncClientAdapter")

from typing import TYPE_CHECKING, Literal

from foghttp_benchmark.constants import ASYNC_MODE, SYNC_MODE


if TYPE_CHECKING:
    from foghttp_benchmark.models import ClientStats, ResponseOutcome, Scenario


class AsyncClientAdapter:
    mode: Literal["async"] = ASYNC_MODE

    async def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> "ClientStats | None":
        return None


class SyncClientAdapter:
    mode: Literal["sync"] = SYNC_MODE

    def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    def close(self) -> object | None:
        raise NotImplementedError

    def stats(self) -> "ClientStats | None":
        return None
