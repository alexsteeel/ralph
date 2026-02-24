"""Tests for --version flag in ralph-tasks CLI entry points."""

import importlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import ralph_tasks


def test_version_from_metadata():
    """__version__ is read from package metadata."""
    assert isinstance(ralph_tasks.__version__, str)
    assert ralph_tasks.__version__  # non-empty


def test_version_fallback():
    """Version falls back to 0.0.0 when package not found."""
    with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
        importlib.reload(ralph_tasks)
        assert ralph_tasks.__version__ == "0.0.0"

    # Restore outside patch context so real metadata is used
    importlib.reload(ralph_tasks)


def test_web_version_flag():
    """ralph-tasks-web --version prints version and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "ralph_tasks.web", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "ralph-tasks-web " in result.stdout
    assert result.stderr == "", f"Unexpected stderr: {result.stderr}"
