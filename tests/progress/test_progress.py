from io import StringIO

from rich.console import Console

from foghttp_benchmark.progress import BenchmarkProgress


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_plain_progress_emits_stage_milestones() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    with BenchmarkProgress(enabled=True, console=console) as progress:
        progress.status("Preparing benchmark")
        with progress.stage("Request runs", total=3) as step:
            step.update("async/foghttp json-small concurrency=1 repeat=1/1")
            step.advance()
            step.update("async/httpx json-small concurrency=1 repeat=1/1")
            step.advance()
            step.update("async/aiohttp json-small concurrency=1 repeat=1/1")
            step.advance()

    output = stream.getvalue()

    assert "Stage: Preparing benchmark" in output
    assert "Request runs: starting (3 steps)" in output
    assert "Request runs: 1/3" in output
    assert "Request runs: done (3/3)" in output
    assert "async/aiohttp json-small concurrency=1 repeat=1/1" in output


def test_disabled_progress_is_silent() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    with BenchmarkProgress(enabled=False, console=console) as progress:
        progress.status("Preparing benchmark")
        with progress.stage("Request runs", total=1) as step:
            step.update("async/foghttp json-small concurrency=1 repeat=1/1")
            step.advance()

    assert stream.getvalue() == ""


def test_plain_progress_uses_reporter_default_milestone() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    with (
        BenchmarkProgress(enabled=True, console=console, milestone_percent=50) as progress,
        progress.stage("Request runs", total=4) as step,
    ):
        step.advance("run=1")
        step.advance("run=2")
        step.advance("run=3")
        step.advance("run=4")

    output = stream.getvalue()

    assert "Request runs: 1/4" in output
    assert "Request runs: 2/4" in output
    assert "Request runs: 3/4" not in output
    assert "Request runs: 4/4" in output


def test_plain_heartbeat_suppresses_short_inner_stages() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    clock = ManualClock()

    with (
        BenchmarkProgress(enabled=True, console=console, monotonic=clock) as progress,
        progress.stage(
            "Measured load",
            total=4,
            plain_output="heartbeat",
        ) as step,
    ):
        step.update("async/foghttp delay-20ms concurrency=1 repeat=1/1")
        step.advance()
        clock.advance(1.0)
        step.advance()
        clock.advance(1.0)
        step.advance()
        clock.advance(1.0)
        step.advance()

    assert stream.getvalue() == ""


def test_plain_heartbeat_emits_long_inner_stage_updates() -> None:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    clock = ManualClock()

    with (
        BenchmarkProgress(
            enabled=True,
            console=console,
            plain_heartbeat_after_s=5.0,
            plain_heartbeat_interval_s=10.0,
            monotonic=clock,
        ) as progress,
        progress.stage("Measured load", total=4, plain_output="heartbeat") as step,
    ):
        step.update("async/foghttp delay-20ms concurrency=1 repeat=1/1")
        step.advance()
        clock.advance(6.0)
        step.advance()
        clock.advance(1.0)
        step.advance()
        clock.advance(10.0)
        step.advance()

    output = stream.getvalue()

    assert "Measured load: starting" not in output
    assert "Measured load: 2/4 (50%) async/foghttp delay-20ms concurrency=1 repeat=1/1" in output
    assert "Measured load: done (4/4)" in output
