import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from foghttp_benchmark.clients.registry import available_clients
from foghttp_benchmark.clients.zapros_client import (
    ZAPROS_PYREQWEST_CLIENT,
    ZaprosSyncAdapter,
    make_zapros_pyreqwest_async,
    make_zapros_pyreqwest_sync,
)
from foghttp_benchmark.constants import ASYNC_MODE, DEFAULT_CLIENTS, SYNC_MODE
from foghttp_benchmark.models import ClientConfig
from foghttp_benchmark.scenarios import scenarios


CONCURRENT_REQUESTS = 20
HTTP_OK = 200


def test_default_matrix_includes_zapros_pyreqwest_after_zapros() -> None:
    clients = DEFAULT_CLIENTS.split(",")

    assert clients[clients.index("zapros") + 1] == ZAPROS_PYREQWEST_CLIENT


def test_available_clients_registers_zapros_pyreqwest_as_distinct_client() -> None:
    clients, skipped = available_clients(["zapros", ZAPROS_PYREQWEST_CLIENT], [ASYNC_MODE, SYNC_MODE])

    assert skipped == {}
    assert [(client.mode, client.name) for client in clients] == [
        (ASYNC_MODE, "zapros"),
        (ASYNC_MODE, ZAPROS_PYREQWEST_CLIENT),
        (SYNC_MODE, "zapros"),
        (SYNC_MODE, ZAPROS_PYREQWEST_CLIENT),
    ]


def test_zapros_pyreqwest_factories_create_closeable_clients() -> None:
    config = ClientConfig(
        concurrency=1,
        request_limit=1,
        follow_redirects=False,
        max_redirects=20,
    )

    sync_client = make_zapros_pyreqwest_sync(config)
    sync_client.close()

    async_client = make_zapros_pyreqwest_async(config)
    asyncio.run(async_client.close())


def test_zapros_sync_adapter_can_serialize_first_lazy_request() -> None:
    adapter = ZaprosSyncAdapter(FirstCallUnsafeClient(), serialize_first_request=True)
    scenario = scenarios()["json-small"]

    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        outcomes = list(
            executor.map(
                lambda _request_index: adapter.request(scenario, "http://127.0.0.1/json-small"),
                range(CONCURRENT_REQUESTS),
            ),
        )

    assert all(outcome.status_code == HTTP_OK for outcome in outcomes)


class FirstCallUnsafeClient:
    def __init__(self) -> None:
        self._lock = Lock()
        self._initialized = False
        self._active_first_calls = 0

    def request(self, _method: str, _url: str, **_kwargs: object) -> object:
        with self._lock:
            if self._initialized:
                return FakeZaprosResponse()
            self._active_first_calls += 1
            if self._active_first_calls > 1:
                msg = "Already borrowed"
                raise RuntimeError(msg)
        time.sleep(0.01)
        with self._lock:
            self._initialized = True
            self._active_first_calls -= 1
        return FakeZaprosResponse()


class FakeZaprosResponse:
    status = HTTP_OK
    content = b"{}"
