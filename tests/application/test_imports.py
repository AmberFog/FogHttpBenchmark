from pathlib import Path
import subprocess
import sys


def test_application_imports_without_cli_frameworks_or_starting_work() -> None:
    fixture = Path(__file__).with_name("import_smoke.py.txt")
    result = subprocess.run(  # noqa: S603  # Only the current interpreter and repository-owned fixture are executed.
        [sys.executable, "-c", fixture.read_text()],
        check=False,
        capture_output=True,
        text=True,
        cwd=fixture.parents[2],
        timeout=20,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "application-import-ok\n"
    assert result.stderr == ""
