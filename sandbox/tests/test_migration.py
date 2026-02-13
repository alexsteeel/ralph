"""Migration-specific tests for ralph-sandbox package."""

import subprocess
from pathlib import Path

import ralph_sandbox


def test_package_imports():
    """Test that all main modules can be imported."""
    from ralph_sandbox import cli, config, templates, utils

    assert all([cli, config, templates, utils])


def test_package_version():
    """Test package version is set correctly."""
    assert ralph_sandbox.__version__ == "0.0.1"


def test_package_all_exports():
    """Test __all__ exports are valid module names."""
    for name in ralph_sandbox.__all__:
        assert isinstance(name, str)


def test_package_resources_dockerfiles():
    """Test that dockerfiles directory is accessible."""
    pkg = Path(ralph_sandbox.__file__).parent
    dockerfiles = pkg / "dockerfiles"
    assert dockerfiles.exists(), f"dockerfiles not found at {dockerfiles}"
    assert dockerfiles.is_dir()
    assert len(list(dockerfiles.iterdir())) > 0


def test_package_resources_templates():
    """Test that templates directory is accessible."""
    pkg = Path(ralph_sandbox.__file__).parent
    templates = pkg / "templates"
    assert templates.exists(), f"templates not found at {templates}"


def test_package_resources_dir():
    """Test that resources directory is accessible."""
    pkg = Path(ralph_sandbox.__file__).parent
    resources = pkg / "resources"
    assert resources.exists(), f"resources not found at {resources}"


def test_package_docker_compose_base():
    """Test that docker-compose.base.yaml is accessible."""
    pkg = Path(ralph_sandbox.__file__).parent
    compose = pkg / "docker-compose.base.yaml"
    assert compose.exists(), f"docker-compose.base.yaml not found at {compose}"


def test_cli_entry_point():
    """Test CLI entry point works after install."""
    result = subprocess.run(
        ["uv", "run", "ai-sbx", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0.0.1" in result.stdout


def test_cli_help():
    """Test CLI help output."""
    result = subprocess.run(
        ["uv", "run", "ai-sbx", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "init" in result.stdout
    assert "image" in result.stdout
    assert "worktree" in result.stdout


def test_no_old_imports():
    """Test that no old ai_sbx imports remain in source files."""
    sandbox_dir = Path(ralph_sandbox.__file__).parent
    for py_file in sandbox_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "from ai_sbx" not in content, f"Old import found in {py_file}"
        assert "import ai_sbx" not in content, f"Old import found in {py_file}"
