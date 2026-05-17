__all__ = ("AsyncClientAdapter", "SyncClientAdapter")

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from foghttp_benchmark.models import ClientStats, ResponseOutcome, Scenario


class AsyncClientAdapter:
    async def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> "ClientStats | None":
        return None


class SyncClientAdapter:
    def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    def close(self) -> object | None:
        raise NotImplementedError

    def stats(self) -> "ClientStats | None":
        return None
