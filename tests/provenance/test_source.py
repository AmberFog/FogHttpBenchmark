from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from foghttp_benchmark import provenance
from foghttp_benchmark.models import JsonObject


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - temporary local repositories and explicit argument vectors.
        ["/usr/bin/git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def source_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, JsonObject]:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "--initial-branch", "release/0.4.2")
    (repo / "Cargo.lock").write_text("version = 4\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "foghttp"\nversion = "0.4.2"\n')
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "baseline")
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "--detach", sha)
    monkeypatch.setattr(provenance, "FOGHTTP_BASELINE", replace(provenance.FOGHTTP_BASELINE, sha=sha))
    return repo, {
        "repository": provenance.FOGHTTP_BASELINE.repository,
        "ref": provenance.FOGHTTP_BASELINE.ref,
        "sha": sha,
        "tip": sha,
        "dirty": False,
        "checkout": str(repo),
        "tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "cargo_lock_sha256": provenance.file_sha256(repo / "Cargo.lock"),
        "pyproject_sha256": provenance.file_sha256(repo / "pyproject.toml"),
    }


def test_clean_exact_detached_local_source_is_accepted(source_checkout: tuple[Path, JsonObject]) -> None:
    _repo, source = source_checkout

    provenance.verify_source(source, check_remote=False)


@pytest.mark.parametrize("field", ["repository", "ref", "tip", "sha"])
def test_source_baseline_cannot_silently_change(source_checkout: tuple[Path, JsonObject], field: str) -> None:
    _repo, source = source_checkout
    source[field] = "different-source"

    with pytest.raises(ValueError):
        provenance.verify_source(source, check_remote=False)


@pytest.mark.parametrize("changed", ["attached", "dirty", "commit", "tree", "cargo-lock", "pyproject"])
def test_source_checkout_and_inputs_must_remain_exact(source_checkout: tuple[Path, JsonObject], changed: str) -> None:
    repo, source = source_checkout
    if changed == "attached":
        git(repo, "switch", "release/0.4.2")
    elif changed == "dirty":
        (repo / "unexpected.py").write_text("unexpected source\n")
    elif changed == "commit":
        git(
            repo,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "another revision",
        )
    elif changed == "tree":
        source["tree"] = "different-tree"
    elif changed == "cargo-lock":
        source["cargo_lock_sha256"] = "different-lock"
    else:
        source["pyproject_sha256"] = "different-pyproject"

    with pytest.raises(ValueError):
        provenance.verify_source(source, check_remote=False)


@pytest.mark.parametrize("remote_state", ["same", "advanced", "missing"])
def test_live_branch_tip_is_checked_without_fetching_or_replacing_baseline(
    source_checkout: tuple[Path, JsonObject],
    monkeypatch: pytest.MonkeyPatch,
    remote_state: str,
) -> None:
    repo, source = source_checkout
    original_git_text = provenance.git_text
    remote_calls: list[tuple[Path, tuple[str, ...]]] = []

    def git_text(checkout: Path, *args: str) -> str:
        if args[0] != "ls-remote":
            return original_git_text(checkout, *args)
        remote_calls.append((checkout, args))
        if remote_state == "missing":
            return ""
        observed = source["sha"] if remote_state == "same" else "0" * 40
        return f"{observed}\t{provenance.FOGHTTP_BASELINE.ref}"

    monkeypatch.setattr(provenance, "git_text", git_text)
    if remote_state == "same":
        provenance.verify_source(source, check_remote=True)
    else:
        with pytest.raises(ValueError):
            provenance.verify_source(source, check_remote=True)

    assert remote_calls == [
        (repo, ("ls-remote", provenance.FOGHTTP_BASELINE.repository, provenance.FOGHTTP_BASELINE.ref)),
    ]
    assert git(repo, "rev-parse", "HEAD") == source["sha"]
    assert git(repo, "branch", "--show-current") == ""
