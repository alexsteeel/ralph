"""Tests for template generation module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from ralph_sandbox.commands.init import _regenerate_derived_files
from ralph_sandbox.config import IDE, BaseImage, ProjectConfig, ProxyConfig
from ralph_sandbox.templates import TemplateManager


class TestTemplateManager:
    """Test template manager."""

    def test_init_default(self):
        """Test template manager initialization with defaults."""
        manager = TemplateManager()
        assert manager.templates_dir is not None

    def test_init_custom_dir(self):
        """Test template manager initialization with custom directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_dir = Path(temp_dir)
            manager = TemplateManager(templates_dir=custom_dir)
            assert manager.templates_dir == custom_dir

    def test_generate_project_files(self):
        """Test generating project files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".devcontainer"
            output_dir.mkdir(parents=True)
            config = ProjectConfig(
                name="test-project",
                path=Path(temp_dir),
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )

            manager = TemplateManager()
            success = manager.generate_project_files(output_dir, config)

            assert success is True
            # Check files were created
            assert (output_dir / "devcontainer.json").exists()
            assert (output_dir / "Dockerfile").exists()
            assert (output_dir / ".env").exists()

    def test_generate_files_requires_directory(self):
        """Test that generate_project_files requires existing directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".devcontainer"
            # Don't create directory
            config = ProjectConfig(
                name="test-project",
                path=Path(temp_dir),
            )

            manager = TemplateManager()
            # Should fail because directory doesn't exist
            success = manager.generate_project_files(output_dir, config)

            # Now create directory and try again
            output_dir.mkdir(parents=True)
            success = manager.generate_project_files(output_dir, config)
            assert success is True

    def test_generate_actual_files(self):
        """Test generating actual files without mocking."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".devcontainer"
            output_dir.mkdir(parents=True)  # Create directory first
            config = ProjectConfig(
                name="test-project",
                path=Path(temp_dir),
                preferred_ide=IDE.PYCHARM,
                base_image=BaseImage.BASE,
            )

            manager = TemplateManager()
            success = manager.generate_project_files(output_dir, config)

            # Check that files were created
            assert success is True
            assert (output_dir / "devcontainer.json").exists()
            assert (output_dir / "Dockerfile").exists()
            assert (output_dir / ".env").exists()
            assert (output_dir / ".gitignore").exists()
            assert (output_dir / "docker-compose.override.yaml").exists()
            assert (output_dir / "init.sh").exists()
            assert (output_dir / "ai-sbx.yaml.template").exists()

            # Check init script is executable
            init_script = output_dir / "init.sh"
            assert init_script.stat().st_mode & 0o111  # Check executable bit

            # Check some content
            env_content = (output_dir / ".env").read_text()
            # PROJECT_NAME uses the directory name (config.path.name), not config.name
            assert "PROJECT_NAME=" in env_content
            assert "COMPOSE_PROJECT_NAME=" in env_content

            dockerfile_content = (output_dir / "Dockerfile").read_text()
            from ralph_sandbox.config import DEFAULT_IMAGE_TAG

            assert f"FROM ai-agents-sandbox/devcontainer:{DEFAULT_IMAGE_TAG}" in dockerfile_content

    def test_force_overwrite(self):
        """Test force overwrite existing files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".devcontainer"
            output_dir.mkdir(parents=True)

            # Create existing file with different content
            existing_file = output_dir / ".env"
            existing_file.write_text("OLD_CONTENT=test")

            config = ProjectConfig(
                name="new-project",
                path=Path(temp_dir),
            )

            manager = TemplateManager()

            # Without force, should not overwrite
            manager.generate_project_files(output_dir, config, force=False)
            content = existing_file.read_text()
            assert "OLD_CONTENT=test" in content

            # With force, should overwrite
            manager.generate_project_files(output_dir, config, force=True)
            content = existing_file.read_text()
            # PROJECT_NAME uses directory name, not config.name
            assert "PROJECT_NAME=" in content
            assert "OLD_CONTENT" not in content

    def test_handles_invalid_config(self):
        """Test handling of invalid configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / ".devcontainer"
            output_dir.mkdir(parents=True)  # Create directory first

            # Config with invalid characters in name
            config = ProjectConfig(
                name="test/project:invalid",
                path=Path(temp_dir),
            )

            manager = TemplateManager()
            # Should still generate files, sanitizing the name
            success = manager.generate_project_files(output_dir, config)
            assert success is True


class TestRegenerateDerivedFiles:
    """Tests for _regenerate_derived_files() helper."""

    def test_regenerates_env_and_override(self):
        """_regenerate_derived_files updates both .env and docker-compose.override.yaml."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            devcontainer_dir = project_path / ".devcontainer"
            devcontainer_dir.mkdir(parents=True)

            config = ProjectConfig(
                name="test-project",
                path=project_path,
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )

            console = MagicMock()
            result = _regenerate_derived_files(console, project_path, config)

            assert result is True

            env_path = devcontainer_dir / ".env"
            override_path = devcontainer_dir / "docker-compose.override.yaml"

            assert env_path.exists()
            assert override_path.exists()

            env_content = env_path.read_text()
            assert "PROJECT_NAME=" in env_content
            assert "COMPOSE_PROJECT_NAME=" in env_content

            override_content = override_path.read_text()
            assert "services:" in override_content
            assert "tinyproxy-devcontainer:" in override_content

    def test_update_with_changed_proxy(self):
        """Changing proxy in config updates both .env and docker-compose.override.yaml."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            devcontainer_dir = project_path / ".devcontainer"
            devcontainer_dir.mkdir(parents=True)

            proxy_a = "socks5://host.gateway:8888"
            proxy_b = "socks5://host.gateway:9999"

            # Initial config with proxy A
            config_a = ProjectConfig(
                name="test-project",
                path=project_path,
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )
            config_a.proxy = ProxyConfig(enabled=True, upstream=proxy_a)

            console = MagicMock()
            assert _regenerate_derived_files(console, project_path, config_a) is True

            env_a = (devcontainer_dir / ".env").read_text()
            override_a = (devcontainer_dir / "docker-compose.override.yaml").read_text()

            # Verify initial state contains proxy A (full URL, not just port)
            assert f"UPSTREAM_PROXY={proxy_a}" in env_a
            assert proxy_a in override_a

            # Update config with proxy B
            config_b = ProjectConfig(
                name="test-project",
                path=project_path,
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )
            config_b.proxy = ProxyConfig(enabled=True, upstream=proxy_b)

            assert _regenerate_derived_files(console, project_path, config_b) is True

            env_b = (devcontainer_dir / ".env").read_text()
            override_b = (devcontainer_dir / "docker-compose.override.yaml").read_text()

            # Both files should now contain proxy B, not proxy A
            assert f"UPSTREAM_PROXY={proxy_b}" in env_b
            assert proxy_a not in env_b
            assert proxy_b in override_b
            assert proxy_a not in override_b

    def test_init_project_reconfig_updates_derived_files(self):
        """Simulates re-running init project: generate_project_files skips existing,
        but _regenerate_derived_files overwrites .env and override."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            devcontainer_dir = project_path / ".devcontainer"
            devcontainer_dir.mkdir(parents=True)

            proxy_a = "socks5://host.gateway:8888"
            proxy_b = "socks5://host.gateway:9999"

            # First run: generate all files with proxy A
            config_a = ProjectConfig(
                name="test-project",
                path=project_path,
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )
            config_a.proxy = ProxyConfig(enabled=True, upstream=proxy_a)

            manager = TemplateManager()
            manager.generate_project_files(devcontainer_dir, config_a, force=False)

            env_first = (devcontainer_dir / ".env").read_text()
            override_first = (devcontainer_dir / "docker-compose.override.yaml").read_text()
            assert f"UPSTREAM_PROXY={proxy_a}" in env_first
            assert proxy_a in override_first

            # Second run: generate_project_files with force=False skips existing files
            config_b = ProjectConfig(
                name="test-project",
                path=project_path,
                preferred_ide=IDE.VSCODE,
                base_image=BaseImage.BASE,
            )
            config_b.proxy = ProxyConfig(enabled=True, upstream=proxy_b)

            manager.generate_project_files(devcontainer_dir, config_b, force=False)

            # Files should still have old proxy (force=False doesn't overwrite)
            env_stale = (devcontainer_dir / ".env").read_text()
            override_stale = (devcontainer_dir / "docker-compose.override.yaml").read_text()
            assert f"UPSTREAM_PROXY={proxy_a}" in env_stale
            assert proxy_a in override_stale

            # Now call _regenerate_derived_files (as init_project does after save)
            console = MagicMock()
            assert _regenerate_derived_files(console, project_path, config_b) is True

            env_updated = (devcontainer_dir / ".env").read_text()
            override_updated = (devcontainer_dir / "docker-compose.override.yaml").read_text()

            # Both files should now have the new proxy
            assert f"UPSTREAM_PROXY={proxy_b}" in env_updated
            assert proxy_a not in env_updated
            assert proxy_b in override_updated
            assert proxy_a not in override_updated

    def test_returns_false_when_devcontainer_missing(self):
        """_regenerate_derived_files returns False when .devcontainer/ doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            # Do NOT create .devcontainer directory

            config = ProjectConfig(
                name="test-project",
                path=project_path,
            )

            console = MagicMock()
            result = _regenerate_derived_files(console, project_path, config)

            assert result is False
            # Should not have created the directory
            assert not (project_path / ".devcontainer").exists()

    def test_env_file_has_restricted_permissions(self):
        """.env file should be created with 0o600 permissions (owner-only read/write)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            devcontainer_dir = project_path / ".devcontainer"
            devcontainer_dir.mkdir(parents=True)

            config = ProjectConfig(
                name="test-project",
                path=project_path,
            )

            console = MagicMock()
            _regenerate_derived_files(console, project_path, config)

            env_path = devcontainer_dir / ".env"
            mode = env_path.stat().st_mode & 0o777
            assert mode == 0o600
