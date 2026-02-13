"""Tests for ralph-cli package skeleton."""

from pathlib import Path


def test_import():
    import ralph_cli

    assert ralph_cli.__version__ == "0.0.1"


def test_package_dir_exists():
    pkg_dir = Path(__file__).parent.parent / "ralph_cli"
    assert pkg_dir.is_dir()
    assert (pkg_dir / "__init__.py").is_file()


def test_pyproject_toml_exists():
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    assert pyproject.is_file()
    content = pyproject.read_text()
    assert 'name = "ralph-cli"' in content
    assert 'version = "0.0.1"' in content


def test_workspace_dependency():
    """ralph-cli depends on ralph-tasks via workspace."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    content = pyproject.read_text()
    assert '"ralph-tasks"' in content
    assert "ralph-tasks = { workspace = true }" in content
