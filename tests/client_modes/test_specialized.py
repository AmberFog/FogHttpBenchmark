import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from tests.client_modes.specialized_support import SpecializedEvents, Suite, run_specialized_case


if TYPE_CHECKING:
    from foghttp_benchmark.models import ClientStats


@pytest.mark.parametrize("suite", ["streaming", "one-upstream", "proxy-connect"])
@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("stats_available", [False, True])
def test_specialized_mode_preserves_dispatch_lifecycle_order_and_stats(
    suite: Suite,
    mode: str,
    *,
    stats_available: bool,
) -> None:
    expected_stats: ClientStats | None = {"connections_opened": 1} if stats_available else None
    events = SpecializedEvents(available_stats=expected_stats)
    main_thread = threading.get_ident()
    result = asyncio.run(run_specialized_case(suite, mode, events))

    assert result.mode == mode
    assert result.client_stats == expected_stats
    assert result.errors == result.warmup_errors == 0
    operation = "stream" if suite == "streaming" else "request"
    assert [name for name, _ in events.events] == ["create", operation, operation, operation, "stats", "close"]
    assert all((thread == main_thread) == (mode == "async") for name, thread in events.events if name == operation)
    assert all(thread == main_thread for name, thread in events.events if name in {"create", "stats", "close"})


@pytest.mark.parametrize("suite", ["streaming", "one-upstream", "proxy-connect"])
@pytest.mark.parametrize("mode", ["async", "sync"])
def test_specialized_stats_failure_still_closes_once(suite: Suite, mode: str) -> None:
    events = SpecializedEvents(stats_failure=True)
    with pytest.raises(RuntimeError, match="injected stats failure"):
        asyncio.run(run_specialized_case(suite, mode, events))

    operation = "stream" if suite == "streaming" else "request"
    assert [name for name, _ in events.events] == ["create", operation, operation, operation, "stats", "close"]
