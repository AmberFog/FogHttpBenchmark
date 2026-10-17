import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from foghttp_benchmark import research_build


@pytest.fixture
def benchmark_root(tmp_path: Path) -> Path:
    root = tmp_path / "benchmark"
    root.mkdir()
    subprocess.run(  # noqa: S603 - real temporary Git repository for ignore semantics.
        ["/usr/bin/git", "-C", str(root), "init", "--initial-branch=review"],
        check=True,
        capture_output=True,
    )
    (root / ".gitignore").write_text("results/\nnested/research/\n", encoding="utf-8")
    return root


@pytest.fixture
def research_commands(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def reject(*_args: Any, **_kwargs: Any) -> None:
        calls.append("external-research-command")
        pytest.fail("Root and output preflight must precede native toolchain or research commands")

    monkeypatch.setattr(research_build, "_toolchain", reject)
    monkeypatch.setattr(research_build, "_run", reject)
    return calls


@pytest.mark.parametrize("relative", ["results/campaign", "nested/research/campaign", "../external/campaign"])
def test_ignored_or_external_output_passes_preflight_without_mutating_files(
    benchmark_root: Path,
    relative: str,
) -> None:
    output = (benchmark_root / relative).resolve()

    research_build._check_output_location(output, benchmark_root)  # noqa: SLF001 - real Git output boundary.

    assert not output.exists()


@pytest.mark.parametrize("relative", ["artifacts/campaign", "results-adjacent/campaign", "nested/unignored/campaign"])
def test_unignored_output_fails_before_creating_files_or_starting_tools(
    benchmark_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    research_commands: list[str],
) -> None:
    output = benchmark_root / relative
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})

    with pytest.raises(ValueError, match="must be Git-ignored"):
        research_build.prepare_research_environment(output, Path(sys.executable), benchmark_root)

    assert not output.exists()
    assert research_commands == []


def test_ignored_symlink_cannot_hide_unignored_output_inside_checkout(
    benchmark_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_commands: list[str],
) -> None:
    ignored = benchmark_root / "results"
    ignored.mkdir()
    (ignored / "alias").symlink_to(benchmark_root / "artifacts", target_is_directory=True)
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})

    with pytest.raises(ValueError, match="must be Git-ignored"):
        research_build.prepare_research_environment(
            ignored / "alias" / "campaign",
            Path(sys.executable),
            benchmark_root,
        )

    assert not (benchmark_root / "artifacts").exists()
    assert research_commands == []


@pytest.mark.parametrize("external_output", [False, True])
def test_missing_git_repository_does_not_turn_ignore_verification_into_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_commands: list[str],
    *,
    external_output: bool,
) -> None:
    root = tmp_path / "not-a-repository"
    root.mkdir()
    (root / ".gitignore").write_text("results/\n", encoding="utf-8")
    output = tmp_path / "external-campaign" if external_output else root / "results" / "campaign"
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})

    with pytest.raises(ValueError, match="requires the benchmark Git repository root"):
        research_build.prepare_research_environment(output, Path(sys.executable), root)

    assert not output.exists()
    assert research_commands == []


@pytest.mark.parametrize("external_output", [False, True])
def test_nested_directory_cannot_stand_in_for_the_benchmark_repository_root(
    benchmark_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_commands: list[str],
    *,
    external_output: bool,
) -> None:
    nested = benchmark_root / "nested"
    nested.mkdir()
    output = tmp_path / "external-campaign" if external_output else nested / "research" / "campaign"
    monkeypatch.setattr(os, "environ", {"PATH": os.environ["PATH"]})

    with pytest.raises(ValueError, match="requires the benchmark Git repository root"):
        research_build.prepare_research_environment(output, Path(sys.executable), nested)

    assert not output.exists()
    assert research_commands == []
