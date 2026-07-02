__all__ = (
    "CHILD_PROCESS_ISOLATION",
    "PER_CLIENT_SCENARIO_ISOLATION",
    "SUPPORTED_ISOLATION_MODES",
    "ChildProcessResult",
    "ChildResourcePeaks",
    "ClientIsolationPlanItem",
    "ClientIsolationSelection",
    "IsolationMode",
)

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias


CHILD_PROCESS_ISOLATION = "subprocess-child"
PER_CLIENT_SCENARIO_ISOLATION = "per-client-scenario"
SUPPORTED_ISOLATION_MODES = (PER_CLIENT_SCENARIO_ISOLATION, CHILD_PROCESS_ISOLATION)

IsolationMode: TypeAlias = Literal["per-client-scenario", "subprocess-child"]


@dataclass(frozen=True, slots=True)
class ClientIsolationSelection:
    clients: list[str]
    skipped: dict[str, str]


@dataclass(frozen=True, slots=True)
class ClientIsolationPlanItem:
    sequence: int
    client: str
    scenario: str | None
    output_dir: Path
    command: list[str]


@dataclass(frozen=True, slots=True)
class ChildResourcePeaks:
    rss_mb: float | None
    threads: int | None
    fds: int | None


@dataclass(frozen=True, slots=True)
class ChildProcessResult:
    sequence: int
    client: str
    scenario: str | None
    output_dir: str
    report_path: str | None
    command: list[str]
    returncode: int
    duration_s: float
    peaks: ChildResourcePeaks
    stdout_tail: str
    stderr_tail: str
