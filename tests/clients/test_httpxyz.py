import importlib
import sys
from types import ModuleType

from foghttp_benchmark.clients.httpxyz_import import import_httpxyz
from foghttp_benchmark.clients.registry import available_clients
from foghttp_benchmark.constants import ASYNC_MODE


def test_import_httpxyz_does_not_shadow_httpx_when_imported_first() -> None:
    original_httpx = sys.modules.get("httpx")
    original_httpxyz = sys.modules.get("httpxyz")
    try:
        sys.modules.pop("httpx", None)
        sys.modules.pop("httpxyz", None)

        httpxyz = import_httpxyz()
        httpx = importlib.import_module("httpx")

        assert sys.modules.get("httpx") is httpx
        assert httpx is not httpxyz
        assert httpx.__name__ == "httpx"
        assert httpxyz.__name__ == "httpxyz"
    finally:
        restore_module("httpx", original_httpx)
        restore_module("httpxyz", original_httpxyz)


def test_available_clients_keeps_httpx_and_httpxyz_distinct() -> None:
    clients, skipped = available_clients(["httpxyz", "httpx"], [ASYNC_MODE])

    assert skipped == {}
    assert [client.name for client in clients] == ["httpxyz", "httpx"]
    assert importlib.import_module("httpx").__name__ == "httpx"


def restore_module(name: str, module: ModuleType | None) -> None:
    if module is None:
        sys.modules.pop(name, None)
        return
    sys.modules[name] = module
