from pathlib import Path
import re
import subprocess
import sys


def test_mode_narrows_factory_and_rejects_opposite_adapter_type(tmp_path: Path) -> None:
    fixtures = Path(__file__).parent
    paths: list[Path] = []
    expected: set[tuple[str, int, str]] = set()
    for name in ("valid", "invalid"):
        source = (fixtures / f"{name}.py.txt").read_text()
        path = tmp_path / f"{name}.py"
        path.write_text(source)
        paths.append(path)
        for number, line in enumerate(source.splitlines(), start=1):
            if "# expect: " in line:
                expected.add((path.name, number, line.split("# expect: ", 1)[1]))
    result = subprocess.run(  # noqa: S603  # Only the current interpreter and repository-owned fixtures are executed.
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(fixtures.parents[1] / "pyproject.toml"),
            "--strict",
            "--no-incremental",
            "--no-pretty",
            "--no-error-summary",
            "--show-error-codes",
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            *(str(path) for path in paths),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    diagnostics = re.findall(r"^(.+):(\d+): error: .*\[([a-z-]+)\]$", result.stdout, flags=re.MULTILINE)
    observed = {(Path(path).name, int(number), code) for path, number, code in diagnostics}
    assert result.returncode == 1, result.stdout + result.stderr
    assert observed == expected, result.stdout + result.stderr
    assert len(diagnostics) == len(expected), result.stdout + result.stderr
