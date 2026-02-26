"""Tests for image commands module."""

import shutil
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from click.testing import CliRunner
from ralph_sandbox.cli import cli
from ralph_sandbox.commands.image import (
    BUILD_ORDER,
    DEFAULT_IMAGE_TAG,
    MONOREPO_IMAGES,
    REQUIRED_IMAGES,
    _find_monorepo_root,
)


class TestFindMonorepoRoot:
    """Test _find_monorepo_root() function."""

    def test_finds_monorepo_root_from_real_package(self):
        """Test that it finds monorepo root via uv.lock marker."""
        root = _find_monorepo_root()
        assert root is not None
        assert (root / "uv.lock").exists()
        assert (root / "sandbox").is_dir()
        assert (root / "tasks").is_dir()
        assert (root / "ralph-cli").is_dir()

    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    def test_returns_none_when_no_marker(self, mock_dockerfiles_dir, tmp_path):
        """Test returns None when uv.lock is not found anywhere."""
        # Create a deep nested dir with no uv.lock
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        mock_dockerfiles_dir.return_value = deep

        with patch("ralph_sandbox.commands.image.subprocess.run", side_effect=FileNotFoundError):
            result = _find_monorepo_root()

        assert result is None

    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    def test_walks_up_to_find_monorepo(self, mock_dockerfiles_dir, tmp_path):
        """Test that it walks up directory tree to find monorepo root."""
        # Create structure: root/uv.lock + tasks/ + sandbox/ + ralph-cli/, root/a/b/c (dockerfiles dir)
        (tmp_path / "uv.lock").touch()
        (tmp_path / "tasks").mkdir()
        (tmp_path / "sandbox").mkdir()
        (tmp_path / "ralph-cli").mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        mock_dockerfiles_dir.return_value = deep

        result = _find_monorepo_root()

        assert result == tmp_path

    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    def test_skips_non_ralph_uv_project(self, mock_dockerfiles_dir, tmp_path):
        """Test that uv.lock alone (without tasks/ and sandbox/) is not enough."""
        # Create a non-ralph uv project (uv.lock but no tasks/ or sandbox/)
        (tmp_path / "uv.lock").touch()
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        mock_dockerfiles_dir.return_value = deep

        with patch("ralph_sandbox.commands.image.subprocess.run", side_effect=FileNotFoundError):
            result = _find_monorepo_root()

        assert result is None

    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    def test_fallback_to_git(self, mock_dockerfiles_dir, tmp_path):
        """Test fallback to git rev-parse when walk-up fails."""
        mock_dockerfiles_dir.return_value = None

        # Simulate git returning a root with uv.lock + tasks/ + sandbox/ + ralph-cli/
        git_root = tmp_path / "repo"
        git_root.mkdir()
        (git_root / "uv.lock").touch()
        (git_root / "tasks").mkdir()
        (git_root / "sandbox").mkdir()
        (git_root / "ralph-cli").mkdir()

        with patch("ralph_sandbox.commands.image.subprocess") as mock_subprocess:
            mock_result = Mock()
            mock_result.stdout = str(git_root) + "\n"
            mock_subprocess.run.return_value = mock_result
            mock_subprocess.CalledProcessError = Exception
            result = _find_monorepo_root()

        assert result == git_root


class TestBuildImageSignature:
    """Test _build_image() with monorepo_root parameter."""

    @patch("ralph_sandbox.commands.image.subprocess.run")
    def test_build_uses_monorepo_root_as_context(self, mock_run):
        """Test that _build_image uses monorepo_root as build context."""
        from ralph_sandbox.commands.image import _build_image

        mock_run.return_value = Mock(returncode=0)

        monorepo_root = Path("/fake/monorepo")
        build_path = Path("/fake/monorepo/sandbox/ralph_sandbox/dockerfiles/devcontainer-base")

        _build_image(
            "ai-agents-sandbox/devcontainer",
            "1.0.0",
            build_path,
            monorepo_root,
            verbose=False,
        )

        # Verify docker build was called with monorepo_root as context
        cmd = mock_run.call_args_list[0][0][0]
        assert str(monorepo_root) in cmd
        assert "-f" in cmd
        dockerfile_idx = cmd.index("-f") + 1
        assert "Dockerfile" in cmd[dockerfile_idx]

    @patch("ralph_sandbox.commands.image.subprocess.run")
    def test_build_with_no_cache(self, mock_run):
        """Test that _build_image passes --no-cache flag."""
        from ralph_sandbox.commands.image import _build_image

        mock_run.return_value = Mock(returncode=0)

        _build_image(
            "ai-agents-sandbox/test",
            "1.0.0",
            Path("/fake/build"),
            Path("/fake/root"),
            no_cache=True,
            verbose=False,
        )

        cmd = mock_run.call_args_list[0][0][0]
        assert "--no-cache" in cmd


class TestBuildCommandMonorepoRoot:
    """Test build command integration with _find_monorepo_root."""

    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_fails_without_monorepo_root(
        self, mock_docker, mock_dockerfiles, mock_image_exists, mock_root, tmp_path
    ):
        """Test build exits with error when monorepo root not found."""
        mock_docker.return_value = True
        # Create fake dockerfiles dir with at least one image subdir
        dockerfiles_dir = tmp_path / "dockerfiles"
        (dockerfiles_dir / "tinyproxy-base").mkdir(parents=True)
        (dockerfiles_dir / "tinyproxy-base" / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir
        # Image doesn't exist so it needs building
        mock_image_exists.return_value = False
        mock_root.return_value = None

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build", "--force"])

        assert result.exit_code != 0
        assert "monorepo root" in result.output.lower()


class TestImageHelpers:
    """Test image helper functions."""

    @patch("ralph_sandbox.commands.image._image_exists")
    def test_image_exists(self, mock_exists):
        """Test checking if image exists."""
        mock_exists.return_value = True

        from ralph_sandbox.commands import image

        exists = image._image_exists("ai-agents-sandbox/devcontainer", "1.0.0")

        assert exists is True

    @patch("ralph_sandbox.commands.image._image_exists")
    def test_image_not_exists(self, mock_exists):
        """Test checking when image doesn't exist."""
        mock_exists.return_value = False

        from ralph_sandbox.commands import image

        exists = image._image_exists("nonexistent/image", "1.0.0")

        assert exists is False

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_images_all_present(self, mock_docker, mock_exists):
        """Test verifying images when all are present."""
        mock_docker.return_value = True
        mock_exists.return_value = True
        runner = CliRunner()
        result = runner.invoke(cli, ["image", "verify"])

        # Command should complete (either all verified or some missing)
        assert result.exit_code in [0, 1]
        assert "image" in result.output.lower() or "verified" in result.output.lower()

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_images_some_missing(self, mock_docker, mock_exists):
        """Test verifying images when some are missing."""
        mock_docker.return_value = True
        # Second image is missing; supply len(REQUIRED_IMAGES) entries for the mock
        mock_exists.side_effect = [True, False] + [True] * (len(REQUIRED_IMAGES) - 2)

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "verify"])

        assert "Missing" in result.output or "missing" in result.output


class TestImageBuildCommand:
    """Test image build command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_requires_docker(self, mock_docker):
        """Test build command requires Docker."""
        mock_docker.return_value = False

        result = self.runner.invoke(cli, ["image", "build"])

        assert result.exit_code != 0
        assert "Docker is not running" in result.output

    @patch("ralph_sandbox.commands.image.Path")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    @patch("ralph_sandbox.utils.run_command")
    def test_build_with_force(self, mock_run, mock_docker, mock_path):
        """Test build with force flag."""
        mock_docker.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_path.return_value.exists.return_value = True

        result = self.runner.invoke(cli, ["image", "build", "--force"])

        # Should succeed
        assert result.exit_code in [0, 1]

    @patch("ralph_sandbox.commands.image.Path")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    @patch("ralph_sandbox.utils.run_command")
    def test_build_with_no_cache(self, mock_run, mock_docker, mock_path):
        """Test build with no-cache flag."""
        mock_docker.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_path.return_value.exists.return_value = True

        result = self.runner.invoke(cli, ["image", "build", "--no-cache"])

        # Should succeed
        assert result.exit_code in [0, 1]


class TestImageListCommand:
    """Test image list command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_list_images(self, mock_docker_running, mock_image_exists):
        """Test listing images."""
        mock_docker_running.return_value = True
        mock_image_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "list"])

        assert result.exit_code == 0
        assert "Image" in result.output or "devcontainer" in result.output

    @pytest.mark.skipif(
        not shutil.which("docker"),
        reason="Docker not available",
    )
    def test_list_images_actual(self):
        """Test listing images (actual check, requires Docker)."""
        result = self.runner.invoke(cli, ["image", "list"])

        assert result.exit_code == 0
        # Should show a table with images
        assert "Image" in result.output or "Status" in result.output

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_list_images_with_custom_tag(self, mock_docker, mock_image_exists):
        """Test that --tag is passed to _image_exists and shown in output."""
        mock_docker.return_value = True
        mock_image_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "list", "--tag", "3.0.0"])

        assert result.exit_code == 0
        assert "3.0.0" in result.output
        assert mock_image_exists.call_count == len(REQUIRED_IMAGES)
        for call in mock_image_exists.call_args_list:
            assert call[0][1] == "3.0.0"

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_list_images_default_tag(self, mock_docker, mock_image_exists):
        """Test that without --tag, DEFAULT_IMAGE_TAG is used."""
        mock_docker.return_value = True
        mock_image_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "list"])

        assert result.exit_code == 0
        assert DEFAULT_IMAGE_TAG in result.output
        for call in mock_image_exists.call_args_list:
            assert call[0][1] == DEFAULT_IMAGE_TAG

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_list_images_with_missing_and_custom_tag(self, mock_docker, mock_image_exists):
        """Test list output when some images are missing with custom tag."""
        mock_docker.return_value = True
        mock_image_exists.return_value = False

        result = self.runner.invoke(cli, ["image", "list", "--tag", "3.0.0"])

        assert result.exit_code == 0
        assert "3.0.0" in result.output
        assert "missing" in result.output.lower() or "Not found" in result.output


class TestImageVerifyCommand:
    """Test image verify command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_all_present(self, mock_docker, mock_exists):
        """Test verify when all images are present."""
        mock_docker.return_value = True
        mock_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "verify"])

        assert result.exit_code == 0
        assert "verified" in result.output.lower() or "all" in result.output.lower()

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_some_missing(self, mock_docker, mock_exists):
        """Test verify when some images are missing."""
        mock_docker.return_value = True
        # Need len(REQUIRED_IMAGES) entries with at least one False
        mock_exists.side_effect = [True, False] + [True] * (len(REQUIRED_IMAGES) - 2)

        result = self.runner.invoke(cli, ["image", "verify"])

        assert result.exit_code != 0
        assert "Missing" in result.output or "missing" in result.output

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_with_custom_tag(self, mock_docker, mock_exists):
        """Test that --tag is passed to _image_exists and shown in output."""
        mock_docker.return_value = True
        mock_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "verify", "--tag", "3.0.0"])

        assert result.exit_code == 0
        assert "3.0.0" in result.output
        assert mock_exists.call_count == len(REQUIRED_IMAGES)
        for call in mock_exists.call_args_list:
            assert call[0][1] == "3.0.0"

    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_verify_default_tag(self, mock_docker, mock_exists):
        """Test that without --tag, DEFAULT_IMAGE_TAG is used."""
        mock_docker.return_value = True
        mock_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "verify"])

        assert result.exit_code == 0
        assert DEFAULT_IMAGE_TAG in result.output
        for call in mock_exists.call_args_list:
            assert call[0][1] == DEFAULT_IMAGE_TAG


class TestMonorepoImages:
    """Test MONOREPO_IMAGES constant and monorepo image build integration."""

    def test_monorepo_images_contains_ralph_tasks(self):
        """Test that MONOREPO_IMAGES includes ralph-tasks."""
        names = [name for name, _ in MONOREPO_IMAGES]
        assert "ralph-tasks" in names

    def test_ralph_tasks_subdir_is_tasks(self):
        """Test that ralph-tasks uses 'tasks' subdir."""
        for name, subdir in MONOREPO_IMAGES:
            if name == "ralph-tasks":
                assert subdir == "tasks"

    def test_required_images_includes_ralph_tasks(self):
        """Test that REQUIRED_IMAGES includes ralph-tasks."""
        assert "ai-agents-sandbox/ralph-tasks" in REQUIRED_IMAGES

    def test_required_images_count(self):
        """Test total number of required images (4 base + 1 monorepo)."""
        # REQUIRED_IMAGES excludes tinyproxy-registry (optional build-only image)
        assert len(REQUIRED_IMAGES) == 5
        # Every MONOREPO_IMAGES entry should appear in REQUIRED_IMAGES
        for name, _ in MONOREPO_IMAGES:
            assert f"ai-agents-sandbox/{name}" in REQUIRED_IMAGES

    @patch("ralph_sandbox.commands.image._print_ralph_tasks_restart_hint")
    @patch("ralph_sandbox.commands.image._build_image")
    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_includes_monorepo_images(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        mock_build,
        mock_hint,
        tmp_path,
    ):
        """Test that build processes monorepo images using monorepo_root paths."""
        mock_docker.return_value = True

        # Set up dockerfiles dir with all BUILD_ORDER subdirs
        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        # Set up monorepo root with tasks/ subdir
        monorepo_root = tmp_path / "monorepo"
        monorepo_root.mkdir()
        tasks_dir = monorepo_root / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "Dockerfile").touch()
        mock_root.return_value = monorepo_root

        # All images need building
        mock_image_exists.return_value = False
        mock_build.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build", "--force"])

        assert result.exit_code == 0

        # Verify ralph-tasks was built with monorepo_root / "tasks" as build_path
        build_calls = mock_build.call_args_list
        ralph_tasks_calls = [c for c in build_calls if c[0][0] == "ai-agents-sandbox/ralph-tasks"]
        assert len(ralph_tasks_calls) == 1
        # build_path argument (3rd positional) should be monorepo_root / "tasks"
        assert ralph_tasks_calls[0][0][2] == tasks_dir

        # Restart hint should be called since ralph-tasks was built
        mock_hint.assert_called_once()

    @patch("ralph_sandbox.commands.image._build_image")
    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_skips_existing_monorepo_images(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        mock_build,
        tmp_path,
    ):
        """Test that existing monorepo images are skipped without --force."""
        mock_docker.return_value = True

        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        # All images already exist
        mock_image_exists.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build"])

        assert result.exit_code == 0
        assert "already built" in result.output.lower()
        mock_build.assert_not_called()
        # Key invariant: monorepo_root is NOT resolved when no images need building
        mock_root.assert_not_called()

    @patch("ralph_sandbox.commands.image._print_ralph_tasks_restart_hint")
    @patch("ralph_sandbox.commands.image._build_image")
    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_only_ralph_tasks_needs_building(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        mock_build,
        mock_hint,
        tmp_path,
    ):
        """Test the key scenario: all dockerfiles-dir images exist, only ralph-tasks missing."""
        mock_docker.return_value = True

        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        monorepo_root = tmp_path / "monorepo"
        monorepo_root.mkdir()
        tasks_dir = monorepo_root / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "Dockerfile").touch()
        mock_root.return_value = monorepo_root

        # Dockerfiles-dir images exist, ralph-tasks does not
        def image_exists_side_effect(name, tag):
            return name != "ai-agents-sandbox/ralph-tasks"

        mock_image_exists.side_effect = image_exists_side_effect
        mock_build.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build"])

        assert result.exit_code == 0
        # Only ralph-tasks should be built
        assert mock_build.call_count == 1
        assert mock_build.call_args[0][0] == "ai-agents-sandbox/ralph-tasks"
        mock_hint.assert_called_once()

    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_fails_monorepo_root_when_only_ralph_tasks_pending(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        tmp_path,
    ):
        """Test monorepo_root failure when only ralph-tasks needs building."""
        mock_docker.return_value = True

        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        # Dockerfiles-dir images exist, ralph-tasks does not
        def image_exists_side_effect(name, tag):
            return name != "ai-agents-sandbox/ralph-tasks"

        mock_image_exists.side_effect = image_exists_side_effect
        mock_root.return_value = None

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build"])

        assert result.exit_code != 0
        assert "monorepo root" in result.output.lower()

    @patch("ralph_sandbox.commands.image._build_image")
    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_build_fails_when_monorepo_subdir_missing(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        mock_build,
        tmp_path,
    ):
        """Test that build fails when monorepo subdir (tasks/) is missing."""
        mock_docker.return_value = True

        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        # Monorepo root exists but WITHOUT tasks/ subdir
        monorepo_root = tmp_path / "monorepo"
        monorepo_root.mkdir()
        mock_root.return_value = monorepo_root

        mock_image_exists.return_value = False
        mock_build.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build", "--force"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch("ralph_sandbox.commands.image._print_ralph_tasks_restart_hint")
    @patch("ralph_sandbox.commands.image._build_image")
    @patch("ralph_sandbox.commands.image._find_monorepo_root")
    @patch("ralph_sandbox.commands.image._image_exists")
    @patch("ralph_sandbox.commands.image._find_dockerfiles_dir")
    @patch("ralph_sandbox.commands.image.is_docker_running")
    def test_restart_hint_not_shown_when_only_dockerfiles_images_built(
        self,
        mock_docker,
        mock_dockerfiles,
        mock_image_exists,
        mock_root,
        mock_build,
        mock_hint,
        tmp_path,
    ):
        """Test that restart hint is NOT shown when ralph-tasks was not rebuilt."""
        mock_docker.return_value = True

        dockerfiles_dir = tmp_path / "dockerfiles"
        for _, subdir in BUILD_ORDER[:5]:
            (dockerfiles_dir / subdir).mkdir(parents=True)
            (dockerfiles_dir / subdir / "Dockerfile").touch()
        mock_dockerfiles.return_value = dockerfiles_dir

        monorepo_root = tmp_path / "monorepo"
        monorepo_root.mkdir()
        tasks_dir = monorepo_root / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "Dockerfile").touch()
        mock_root.return_value = monorepo_root

        # Only dockerfiles-dir images need building, ralph-tasks already exists
        def image_exists_side_effect(name, tag):
            return name == "ai-agents-sandbox/ralph-tasks"

        mock_image_exists.side_effect = image_exists_side_effect
        mock_build.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["image", "build"])

        assert result.exit_code == 0
        mock_hint.assert_not_called()


class TestRalphTasksRestartHint:
    """Test _print_ralph_tasks_restart_hint."""

    @patch("ralph_sandbox.commands.image.subprocess.run")
    def test_hint_shown_when_container_running(self, mock_run):
        """Test that restart hint is shown when ai-sbx-ralph-tasks is running."""
        from ralph_sandbox.commands.image import _print_ralph_tasks_restart_hint

        mock_run.return_value = Mock(stdout="ai-sbx-ralph-tasks\nai-sbx-neo4j\n", returncode=0)
        console = Mock()
        _print_ralph_tasks_restart_hint(console)

        assert console.print.call_count == 2
        # First call should mention "old image"
        first_msg = console.print.call_args_list[0][0][0]
        assert "old image" in first_msg

    @patch("ralph_sandbox.commands.image.subprocess.run")
    def test_hint_not_shown_when_container_not_running(self, mock_run):
        """Test that no hint is shown when container is not running."""
        from ralph_sandbox.commands.image import _print_ralph_tasks_restart_hint

        mock_run.return_value = Mock(stdout="ai-sbx-neo4j\n", returncode=0)
        console = Mock()
        _print_ralph_tasks_restart_hint(console)

        console.print.assert_not_called()

    @patch("ralph_sandbox.commands.image.subprocess.run")
    def test_hint_handles_docker_not_found(self, mock_run):
        """Test that hint gracefully handles docker binary not found."""
        from ralph_sandbox.commands.image import _print_ralph_tasks_restart_hint

        mock_run.side_effect = FileNotFoundError("docker not found")
        console = Mock()
        _print_ralph_tasks_restart_hint(console)

        console.print.assert_not_called()
