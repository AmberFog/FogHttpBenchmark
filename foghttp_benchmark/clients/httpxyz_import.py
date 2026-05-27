__all__ = ("import_httpxyz",)

import importlib
import sys
from types import ModuleType


def import_httpxyz() -> ModuleType:
    existing_httpx = sys.modules.get("httpx")
    module = importlib.import_module("httpxyz")
    restore_httpx_module(existing_httpx, module)
    return module


def restore_httpx_module(existing_httpx: ModuleType | None, httpxyz: ModuleType) -> None:
    if existing_httpx is not None and existing_httpx.__name__ != "httpxyz":
        sys.modules["httpx"] = existing_httpx
        return
    if sys.modules.get("httpx") is httpxyz or getattr(sys.modules.get("httpx"), "__name__", None) == "httpxyz":
        del sys.modules["httpx"]
