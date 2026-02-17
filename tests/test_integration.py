"""Integration tests for monorepo final integration (task #7).

Tests verify:
- Dockerfile pip install URLs point to monorepo
- entrypoint.sh MCP registration uses ralph-tasks
- No hardcoded /home/claude/ paths in hooks
- Root conftest.py exists for pytest discovery
- CLI entry points work
- MCP server is importable and has serve command
- README.md and CLAUDE.md exist with required content
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent


class TestDockerfile:
    """Verify Dockerfile installs packages from monorepo."""

    DOCKERFILE = ROOT / "sandbox/ralph_sandbox/dockerfiles/devcontainer-base/Dockerfile"

    def test_dockerfile_exists(self):
        assert self.DOCKERFILE.is_file()

    def test_installs_ralph_tasks_from_monorepo(self):
        content = self.DOCKERFILE.read_text()
        assert "COPY tasks/ /tmp/ralph-tasks/" in content
        assert "uv pip install" in content and "/tmp/ralph-tasks/" in content

    def test_installs_ralph_cli_from_monorepo(self):
        content = self.DOCKERFILE.read_text()
        assert "COPY ralph-cli/ /tmp/ralph-cli/" in content
        assert "uv pip install" in content and "/tmp/ralph-cli/" in content

    def test_no_old_md_task_mcp_url(self):
        content = self.DOCKERFILE.read_text()
        assert "md-task-mcp.git" not in content

    def test_no_old_claude_cli_url(self):
        content = self.DOCKERFILE.read_text()
        assert "alexsteeel/.claude.git" not in content


class TestEntrypoint:
    """Verify entrypoint.sh MCP registration."""

    ENTRYPOINT = ROOT / "sandbox/ralph_sandbox/dockerfiles/devcontainer-base/entrypoint.sh"

    def test_entrypoint_exists(self):
        assert self.ENTRYPOINT.is_file()

    def test_registers_ralph_tasks_mcp(self):
        content = self.ENTRYPOINT.read_text()
        assert "ralph-tasks" in content
        assert "ralph-tasks serve" in content

    def test_no_old_md_task_mcp_registration(self):
        content = self.ENTRYPOINT.read_text()
        assert "md-task-mcp serve" not in content
        assert "md-task-mcp --" not in content


class TestCodexConfig:
    """Verify codex_config.toml uses ralph-tasks MCP server name."""

    CONFIG = ROOT / "sandbox/ralph_sandbox/dockerfiles/devcontainer-base/conf/codex_config.toml"

    def test_config_exists(self):
        assert self.CONFIG.is_file()

    def test_uses_ralph_tasks_mcp(self):
        content = self.CONFIG.read_text()
        assert "[mcp_servers.ralph-tasks]" in content
        assert 'command = "ralph-tasks"' in content

    def test_no_old_md_task_mcp(self):
        content = self.CONFIG.read_text()
        assert "md-task-mcp" not in content


class TestSettingsExample:
    """Verify settings.example.json uses ralph-tasks MCP server name."""

    SETTINGS = ROOT / "claude/settings.example.json"

    def test_settings_exists(self):
        assert self.SETTINGS.is_file()

    def test_uses_ralph_tasks_mcp(self):
        content = self.SETTINGS.read_text()
        assert '"ralph-tasks"' in content

    def test_no_old_md_task_mcp(self):
        content = self.SETTINGS.read_text()
        assert "md-task-mcp" not in content


class TestHooksNoPaths:
    """Verify hooks have no hardcoded /home/claude/ paths."""

    HOOKS_DIR = ROOT / "claude/hooks"

    def test_no_hardcoded_home_claude(self):
        for hook_file in self.HOOKS_DIR.iterdir():
            if hook_file.suffix in (".py", ".sh"):
                content = hook_file.read_text()
                assert "/home/claude/" not in content, (
                    f"{hook_file.name} contains hardcoded /home/claude/ path"
                )

    def test_check_workflow_uses_path_home(self):
        content = (self.HOOKS_DIR / "check_workflow.py").read_text()
        assert "Path.home()" in content

    def test_check_workflow_ralph_uses_path_home(self):
        content = (self.HOOKS_DIR / "check_workflow_ralph.py").read_text()
        assert "Path.home()" in content

    def test_notify_uses_home_env(self):
        content = (self.HOOKS_DIR / "notify.sh").read_text()
        assert "$HOME" in content


class TestRootConftest:
    """Verify root conftest.py exists."""

    def test_root_conftest_exists(self):
        assert (ROOT / "conftest.py").is_file()

    def test_root_conftest_is_minimal(self):
        content = (ROOT / "conftest.py").read_text()
        assert "pytest" in content.lower() or "conftest" in content.lower()


class TestPyprojectToml:
    """Verify root pyproject.toml has correct testpaths."""

    def test_testpaths_includes_all_packages(self):
        content = (ROOT / "pyproject.toml").read_text()
        for path in ["tasks/tests", "sandbox/tests", "ralph-cli/tests"]:
            assert path in content, f"Missing testpath: {path}"

    def test_import_mode_importlib(self):
        content = (ROOT / "pyproject.toml").read_text()
        assert "importlib" in content


class TestCLIEntryPoints:
    """Verify CLI commands are accessible."""

    def test_ralph_help(self):
        result = subprocess.run(
            ["uv", "run", "ralph", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
        assert result.returncode == 0

    def test_ai_sbx_help(self):
        result = subprocess.run(
            ["uv", "run", "ai-sbx", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
        assert result.returncode == 0

    def test_ralph_tasks_web_importable(self):
        result = subprocess.run(
            ["uv", "run", "python", "-c", "from ralph_tasks.web import main; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
        assert result.returncode == 0
        assert "ok" in result.stdout


class TestMCPServer:
    """Verify MCP server is accessible."""

    def test_ralph_tasks_serve_starts(self):
        """MCP server starts and exits cleanly with timeout."""
        result = subprocess.run(
            ["timeout", "3", "uv", "run", "ralph-tasks", "serve"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=ROOT,
        )
        # timeout returns 124 when it kills the process — that's fine,
        # it means the server started successfully
        assert result.returncode in (0, 124), f"MCP server failed to start: stderr={result.stderr}"


class TestDocumentation:
    """Verify README.md and CLAUDE.md content."""

    def test_readme_exists(self):
        assert (ROOT / "README.md").is_file()

    def test_readme_has_packages_table(self):
        content = (ROOT / "README.md").read_text()
        assert "ralph-tasks" in content
        assert "ralph-sandbox" in content
        assert "ralph-cli" in content

    def test_readme_has_setup_instructions(self):
        content = (ROOT / "README.md").read_text()
        assert "uv sync" in content

    def test_claude_md_is_project_instructions(self):
        content = (ROOT / "CLAUDE.md").read_text()
        # Should NOT contain migration-specific content
        assert "Migration Plan" not in content
        assert "Source Repos Location" not in content
        assert "Open Questions" not in content

    def test_claude_md_has_structure(self):
        content = (ROOT / "CLAUDE.md").read_text()
        assert "## Structure" in content
        assert "## Packages" in content
        assert "## Development" in content

    def test_claude_md_has_docker_instructions(self):
        content = (ROOT / "CLAUDE.md").read_text()
        assert "Docker" in content
        assert "COPY tasks/" in content
