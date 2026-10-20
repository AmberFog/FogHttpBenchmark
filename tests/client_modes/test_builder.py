import asyncio
import threading
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlencode

import pytest

from foghttp_benchmark.request_builder.cases import (
    DEFAULT_HEADERS,
    DEFAULT_PARAMS,
    REQUEST_PARAMS,
    request_builder_cases,
)
from foghttp_benchmark.request_builder.models import (
    AsyncRequestBuilderClientSpec,
    RequestBuilderCase,
    SyncRequestBuilderClientSpec,
)
from foghttp_benchmark.request_builder.runner import run_request_builder_case
from tests.client_modes.support import ClientEvents


class BuilderOperations:
    def __init__(self, events: ClientEvents) -> None:
        self.events = events

    def build(self, case: RequestBuilderCase, base_url: str) -> object:
        self.events.record("build")
        query = urlencode((*DEFAULT_PARAMS, *REQUEST_PARAMS))
        return SimpleNamespace(
            method=case.method,
            url=f"{base_url}/{case.path}?{query}",
            content=b"",
            headers=DEFAULT_HEADERS,
        )

    def send_status(self) -> int:
        self.events.record("send")
        if self.events.request_failure:
            message = "injected send failure"
            raise ValueError(message)
        return 200


class AsyncBuilderClient(BuilderOperations):
    mode: Literal["async"] = "async"

    async def send(self, _request: object) -> int:
        return self.send_status()

    async def close(self) -> None:
        self.events.record("close")


class SyncBuilderClient(BuilderOperations):
    mode: Literal["sync"] = "sync"

    def send(self, _request: object) -> int:
        return self.send_status()

    def close(self) -> None:
        self.events.record("close")


@pytest.mark.parametrize("mode", ["async", "sync"])
@pytest.mark.parametrize("request_failure", [False, True])
def test_builder_spec_preserves_whole_case_thread_dispatch_and_close(mode: str, *, request_failure: bool) -> None:
    events = ClientEvents(request_failure=request_failure)
    main_thread = threading.get_ident()

    def make_async(_config: object) -> AsyncBuilderClient:
        events.before_create()
        return AsyncBuilderClient(events)

    def make_sync(_config: object) -> SyncBuilderClient:
        events.before_create()
        return SyncBuilderClient(events)

    spec = (
        AsyncRequestBuilderClientSpec("fake", make_async)
        if mode == "async"
        else SyncRequestBuilderClientSpec("fake", make_sync)
    )
    result = asyncio.run(
        run_request_builder_case(
            spec=spec,
            base_url="http://benchmark.invalid",
            case=request_builder_cases()["send-prepared-get"],
            iterations=2,
            warmup=1,
            repeat=1,
        ),
    )

    assert result.mode == mode
    assert result.errors == (2 if request_failure else 0)
    assert result.error_types == ({"ValueError": 2} if request_failure else {})
    assert [name for name, _ in events.events] == ["create", "build", "send", "build", "send", "build", "send", "close"]
    assert all((thread == main_thread) == (mode == "async") for _, thread in events.events)
