"""Tests for monorepo workspace structure."""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_root_pyproject_toml():
    pyproject = ROOT / "pyproject.toml"
    assert pyproject.is_file()
    content = pyproject.read_text()
    assert 'name = "ralph"' in content
    assert 'members = ["tasks", "sandbox", "ralph-cli"]' in content


def test_gitignore_exists():
    gitignore = ROOT / ".gitignore"
    assert gitignore.is_file()
    content = gitignore.read_text()
    assert "__pycache__/" in content
    assert ".env" in content
    assert ".venv/" in content


def test_workspace_members_exist():
    for member in ["tasks", "sandbox", "ralph-cli"]:
        member_dir = ROOT / member
        assert member_dir.is_dir(), f"Workspace member {member}/ missing"
        assert (member_dir / "pyproject.toml").is_file(), f"{member}/pyproject.toml missing"


def test_package_dirs_exist():
    packages = {
        "tasks": "ralph_tasks",
        "sandbox": "ralph_sandbox",
        "ralph-cli": "ralph_cli",
    }
    for member, pkg_name in packages.items():
        pkg_dir = ROOT / member / pkg_name
        assert pkg_dir.is_dir(), f"{member}/{pkg_name}/ missing"
        assert (pkg_dir / "__init__.py").is_file(), f"{member}/{pkg_name}/__init__.py missing"


def test_claude_dirs_exist():
    for subdir in ["commands", "hooks", "skills"]:
        d = ROOT / "claude" / subdir
        assert d.is_dir(), f"claude/{subdir}/ missing"


def test_codex_dir_exists():
    assert (ROOT / "codex").is_dir()


def test_all_packages_importable_with_unified_version():
    """All packages importable and share the same version."""
    import ralph_cli
    import ralph_sandbox
    import ralph_tasks

    versions = {ralph_tasks.__version__, ralph_sandbox.__version__, ralph_cli.__version__}
    assert len(versions) == 1, f"Version mismatch: {versions}"
    assert versions.pop() == "0.0.1"
