"""Tests for --version flag in ralph CLI."""

import importlib
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from ralph_cli.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_version_flag():
    """ralph --version prints version and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ralph-cli " in result.output
    version_str = result.output.strip().split(" ", 1)[1]
    assert version_str  # non-empty


def test_version_flag_with_command():
    """--version takes precedence over subcommands (is_eager=True)."""
    result = runner.invoke(app, ["--version", "health"])
    assert result.exit_code == 0
    assert "ralph-cli " in result.output


def test_version_fallback():
    """Version falls back to 0.0.0 when package not found."""
    import ralph_cli

    with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
        importlib.reload(ralph_cli)
        assert ralph_cli.__version__ == "0.0.0"

    # Restore outside patch context so real metadata is used
    importlib.reload(ralph_cli)
