from typer.testing import CliRunner

from foghttp_benchmark.cli import app


def test_cli_help_does_not_expose_isolation_switch() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--isolation" not in result.output


def test_cli_rejects_public_isolation_switch() -> None:
    result = CliRunner().invoke(app, ["--isolation", "none"])

    assert result.exit_code != 0
