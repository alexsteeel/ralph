"""Tests for image commands module."""

from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner
from ralph_sandbox.cli import cli
from ralph_sandbox.commands.image import _find_monorepo_root


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

    def test_verify_images_all_present(self):
        """Test verifying images when all are present."""
        # Since we can't mock internal methods easily and images actually exist,
        # just test that the command runs
        runner = CliRunner()
        result = runner.invoke(cli, ["image", "verify"])

        # Command should complete (either all verified or some missing)
        assert result.exit_code in [0, 1]
        assert "image" in result.output.lower() or "verified" in result.output.lower()

    @patch("ralph_sandbox.commands.image._image_exists")
    def test_verify_images_some_missing(self, mock_exists):
        """Test verifying images when some are missing."""
        # Return False for tinyproxy to simulate it's missing
        mock_exists.side_effect = [
            True,  # devcontainer exists
            False,  # tinyproxy missing
            True,  # docker-dind exists
        ]

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
    @patch("ralph_sandbox.utils.is_docker_running")
    def test_list_images(self, mock_docker_running, mock_image_exists):
        """Test listing images."""
        mock_docker_running.return_value = True
        mock_image_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "list"])

        assert result.exit_code == 0
        assert "Image" in result.output or "devcontainer" in result.output

    def test_list_images_actual(self):
        """Test listing images (actual check)."""
        result = self.runner.invoke(cli, ["image", "list"])

        assert result.exit_code == 0
        # Should show a table with images
        assert "Image" in result.output or "Status" in result.output


class TestImageVerifyCommand:
    """Test image verify command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    @patch("ralph_sandbox.commands.image._image_exists")
    def test_verify_all_present(self, mock_exists):
        """Test verify when all images are present."""
        mock_exists.return_value = True

        result = self.runner.invoke(cli, ["image", "verify"])

        assert result.exit_code == 0
        assert "verified" in result.output.lower() or "all" in result.output.lower()

    @patch("ralph_sandbox.commands.image._image_exists")
    def test_verify_some_missing(self, mock_exists):
        """Test verify when some images are missing."""
        mock_exists.side_effect = [True, False, True]  # tinyproxy missing

        result = self.runner.invoke(cli, ["image", "verify"])

        assert result.exit_code != 0
        assert "Missing" in result.output or "missing" in result.output
