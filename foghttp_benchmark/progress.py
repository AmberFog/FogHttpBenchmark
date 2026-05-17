__all__ = (
    "BenchmarkProgress",
    "PlainOutputMode",
    "ProgressReporter",
    "ProgressStep",
    "is_progress_enabled",
    "progress_stage",
    "progress_status",
)

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from threading import Lock
import time
from types import TracebackType
from typing import Literal, Protocol

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


MILESTONE_PERCENT = 10
INNER_MILESTONE_PERCENT = 25
PLAIN_HEARTBEAT_AFTER_S = 5.0
PLAIN_HEARTBEAT_INTERVAL_S = 15.0

PlainOutputMode = Literal["milestone", "heartbeat"]


class ProgressStep(Protocol):
    def update(self, label: str) -> None: ...

    def advance(self, label: str = "") -> None: ...


class ProgressReporter(Protocol):
    def stage(
        self,
        name: str,
        *,
        total: int,
        milestone_percent: int | None = None,
        plain_output: PlainOutputMode = "milestone",
    ) -> AbstractContextManager[ProgressStep]: ...

    def status(self, message: str) -> None: ...


@dataclass(slots=True)
class StageProgress:
    reporter: "BenchmarkProgress"
    name: str
    total: int
    milestone_percent: int
    plain_output: PlainOutputMode
    task_id: TaskID | None
    started_at: float
    completed: int = 0
    label: str = ""
    last_plain_update_at: float | None = None
    plain_updates_emitted: int = 0
    lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def update(self, label: str) -> None:
        with self.lock:
            self.label = label
            self.reporter.update_stage(self)

    def advance(self, label: str = "") -> None:
        with self.lock:
            if label:
                self.label = label
            self.completed += 1
            self.reporter.advance_stage(self)


class NullProgressStep:
    def update(self, _label: str) -> None:
        return None

    def advance(self, _label: str = "") -> None:
        return None


class BenchmarkProgress:
    def __init__(
        self,
        *,
        enabled: bool,
        console: Console | None = None,
        milestone_percent: int = MILESTONE_PERCENT,
        plain_heartbeat_after_s: float = PLAIN_HEARTBEAT_AFTER_S,
        plain_heartbeat_interval_s: float = PLAIN_HEARTBEAT_INTERVAL_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.console = console or Console(stderr=True, soft_wrap=True)
        self.milestone_percent = milestone_percent
        self.plain_heartbeat_after_s = plain_heartbeat_after_s
        self.plain_heartbeat_interval_s = plain_heartbeat_interval_s
        self.monotonic = monotonic
        self.rich_progress: Progress | None = None
        self.rich_enabled = enabled and self.console.is_terminal

    def __enter__(self) -> "BenchmarkProgress":
        if self.rich_enabled:
            self.rich_progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
            )
            self.rich_progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.rich_progress is not None:
            self.rich_progress.stop()

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        total: int,
        milestone_percent: int | None = None,
        plain_output: PlainOutputMode = "milestone",
    ) -> Iterator[ProgressStep]:
        if not self.enabled:
            yield NullProgressStep()
            return

        task_id = self.add_task(name, total)
        effective_milestone_percent = milestone_percent or self.milestone_percent
        stage = StageProgress(
            reporter=self,
            name=name,
            total=total,
            milestone_percent=effective_milestone_percent,
            plain_output=plain_output,
            task_id=task_id,
            started_at=self.monotonic(),
        )
        self.print_plain_stage_start(stage)
        try:
            yield stage
        except BaseException:
            self.finish_stage(stage, success=False)
            raise
        else:
            self.finish_stage(stage, success=True)

    def status(self, message: str) -> None:
        if not self.enabled:
            return
        self.console.print(f"[bold]Stage:[/] {message}")

    def add_task(self, name: str, total: int) -> TaskID | None:
        if self.rich_progress is None:
            return None
        return self.rich_progress.add_task(name, total=total)

    def update_stage(self, stage: StageProgress) -> None:
        if self.rich_progress is None or stage.task_id is None:
            return
        description = stage.name if not stage.label else f"{stage.name}: {stage.label}"
        self.rich_progress.update(stage.task_id, description=description)

    def advance_stage(self, stage: StageProgress) -> None:
        if self.rich_progress is not None and stage.task_id is not None:
            self.update_stage(stage)
            self.rich_progress.update(stage.task_id, completed=stage.completed)
            return

        if stage.plain_output == "heartbeat":
            self.print_plain_heartbeat(stage)
            return

        if self.should_print_plain_milestone(stage):
            self.print_plain_progress(stage)

    def finish_stage(self, stage: StageProgress, *, success: bool) -> None:
        if self.rich_progress is not None and stage.task_id is not None:
            if success:
                self.rich_progress.update(stage.task_id, completed=stage.total)
            return

        if stage.plain_output == "heartbeat" and success and not self.should_finish_plain_heartbeat(stage):
            return

        status = "done" if success else "failed"
        self.console.print(f"[bold]{stage.name}:[/] {status} ({stage.completed}/{stage.total})")

    def print_plain_stage_start(self, stage: StageProgress) -> None:
        if self.rich_progress is None and stage.plain_output == "milestone":
            self.console.print(f"[bold]{stage.name}:[/] starting ({stage.total} steps)")

    def print_plain_progress(self, stage: StageProgress) -> None:
        percent = plain_percent(stage.completed, stage.total)
        suffix = "" if not stage.label else f" {stage.label}"
        self.console.print(f"[dim]{stage.name}: {stage.completed}/{stage.total} ({percent}%){suffix}[/]")

    def print_plain_heartbeat(self, stage: StageProgress) -> None:
        now = self.monotonic()
        if not self.should_print_plain_heartbeat(stage, now=now):
            return

        self.print_plain_progress(stage)
        stage.last_plain_update_at = now
        stage.plain_updates_emitted += 1

    def should_print_plain_milestone(self, stage: StageProgress) -> bool:
        if stage.completed <= 0:
            return False
        if stage.completed == 1 or stage.completed >= stage.total:
            return True

        current = (stage.completed * 100) // stage.total
        previous = ((stage.completed - 1) * 100) // stage.total
        return (current // stage.milestone_percent) > (previous // stage.milestone_percent)

    def should_print_plain_heartbeat(self, stage: StageProgress, *, now: float) -> bool:
        if stage.completed <= 0 or stage.completed >= stage.total:
            return False

        elapsed = now - stage.started_at
        if elapsed < self.plain_heartbeat_after_s:
            return False
        if stage.last_plain_update_at is None:
            return True
        return (now - stage.last_plain_update_at) >= self.plain_heartbeat_interval_s

    def should_finish_plain_heartbeat(self, stage: StageProgress) -> bool:
        if stage.plain_updates_emitted > 0:
            return True
        return (self.monotonic() - stage.started_at) >= self.plain_heartbeat_after_s


def progress_stage(
    progress: ProgressReporter | None,
    name: str,
    *,
    total: int,
    milestone_percent: int | None = None,
    plain_output: PlainOutputMode = "milestone",
) -> AbstractContextManager[ProgressStep]:
    if progress is None:
        return nullcontext(NullProgressStep())
    return progress.stage(name, total=total, milestone_percent=milestone_percent, plain_output=plain_output)


def progress_status(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress.status(message)


def is_progress_enabled(progress: ProgressReporter | None) -> bool:
    if progress is None:
        return False
    if isinstance(progress, BenchmarkProgress):
        return progress.enabled
    return True


def plain_percent(completed: int, total: int) -> int:
    if total <= 0:
        return 100
    return min(100, (completed * 100) // total)
