__all__ = ("PythonLoadProfile", "active_python_instrumentation")

import cProfile
import hashlib
import os
from pathlib import Path
import platform
import sys
import threading
import time

from foghttp_benchmark.models import JsonObject


def active_python_instrumentation() -> bool:
    if sys.getprofile() is not None or sys.gettrace() is not None:
        return True
    monitoring = getattr(sys, "monitoring", None)
    return monitoring is not None and any(monitoring.get_tool(tool) is not None for tool in range(6))


MAX_PROFILE_BYTES = 16 * 1024 * 1024


class PythonLoadProfile:
    def __init__(self, path: Path) -> None:
        if active_python_instrumentation():
            msg = "Explicit cProfile requires no existing Python profiler or trace hook"
            raise ValueError(msg)
        if path.exists():
            msg = f"Python profile output already exists: {path}"
            raise FileExistsError(msg)
        self.path = path.resolve()
        self.profiler = cProfile.Profile()
        self.enabled_before_ns: int | None = None
        self.disabled_after_ns: int | None = None
        self.thread_id = threading.get_ident()
        self.interpreter_monitoring = hasattr(sys, "monitoring")

    def start(self) -> None:
        self.enabled_before_ns = time.perf_counter_ns()
        self.profiler.enable()

    def stop(self) -> None:
        self.profiler.disable()
        self.disabled_after_ns = time.perf_counter_ns()

    def write(self, *, load_started_ns: int, load_finished_ns: int) -> JsonObject:
        if self.enabled_before_ns is None or self.disabled_after_ns is None:
            msg = "Cannot write a Python profile without completed load boundaries"
            raise RuntimeError(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            msg = f"Python profile output already exists: {self.path}"
            raise FileExistsError(msg)
        self.profiler.dump_stats(str(self.path))
        size = self.path.stat().st_size
        if not 0 < size <= MAX_PROFILE_BYTES:
            msg = "Python profile must be nonempty and bounded by 16 MiB"
            raise ValueError(msg)
        content = self.path.read_bytes()
        if len(content) != size:
            msg = "Python profile output changed while reading"
            raise ValueError(msg)
        return {
            "profiler": "cprofile",
            "status": "ok",
            "path": str(self.path),
            "relative_path": str(self.path.relative_to(self.path.parent.parent)),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "pid": os.getpid(),
            "thread_id": self.thread_id,
            "enabling_thread_id": self.thread_id,
            "thread_id_scope": "Profiler enabling thread; not evidence of event coverage",
            "thread_scope": "interpreter-monitoring" if self.interpreter_monitoring else "enabling-thread",
            "attribution_qualification": (
                "unqualified-cross-thread-context" if self.interpreter_monitoring else "qualified-thread-scope"
            ),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "module": "cProfile",
            "module_path": cProfile.__file__,
            "enabled_before_ns": self.enabled_before_ns,
            "disabled_after_ns": self.disabled_after_ns,
            "load_started_ns": load_started_ns,
            "load_finished_ns": load_finished_ns,
            "load_boundary_overhang_ns": (
                load_started_ns - self.enabled_before_ns + self.disabled_after_ns - load_finished_ns
            ),
            "boundary_scope": "Timestamps bracket profiler enable/disable; include boundary bookkeeping",
            "clock": "time.perf_counter_ns; monotonic; nanoseconds",
            "timer": "cProfile default timer; real time, not process CPU time",
            "scope": (
                "Measured async load including incremental SHA-256 and bounded scalar/diagnostic bookkeeping; "
                + (
                    "interpreter-wide Python callbacks may include other attached threads; "
                    "native worker execution outside Python is excluded; "
                    if self.interpreter_monitoring
                    else "enabling Python thread only; other Python/native worker threads excluded; "
                )
                + "warmup, CPU end probes, digest finalization, replay, lifecycle controls and disk/report I/O excluded"
            ),
            "limitation": (
                "Deterministic profiler changes scheduling and timing; self/cumulative times are not CPU shares; "
                "async suspension/resumption and native waits cannot isolate copies, wakeups or Future costs; "
                "pstats is tied to the recorded Python version; "
                "interpreter monitoring can mix cross-thread caller contexts: self/cumulative/caller data cannot "
                "partition costs or prove a synchronous call chain"
            ),
        }
