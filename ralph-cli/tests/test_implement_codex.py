"""Tests for codex review loop in implement command."""

from unittest.mock import MagicMock, patch

import pytest
from ralph_cli.commands.implement import (
    _build_claude_fix_prompt,
    _build_codex_review_prompt,
    _create_fixup_commit,
    run_claude_fix,
    run_codex_review,
    run_codex_review_loop,
)
from ralph_cli.config import Settings


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        _env_file=None,
        codex_review_max_iterations=3,
        codex_review_model="gpt-5.3-codex",
    )


@pytest.fixture
def session_log():
    """Create mock session log."""
    log = MagicMock()
    log.append = MagicMock()
    return log


class TestBuildCodexReviewPrompt:
    """Tests for _build_codex_review_prompt."""

    def test_first_iteration(self):
        prompt = _build_codex_review_prompt("myproject#1", 1)
        assert "myproject#1" in prompt
        assert "LGTM" in prompt
        assert "НЕ ИЗМЕНЯЙ КОД" in prompt

    def test_subsequent_iteration(self):
        prompt = _build_codex_review_prompt("myproject#1", 2)
        assert "Повторная проверка" in prompt
        assert "итерация 2" in prompt
        assert "LGTM" in prompt

    def test_third_iteration(self):
        prompt = _build_codex_review_prompt("myproject#1", 3)
        assert "итерация 3" in prompt


class TestBuildClaudeFixPrompt:
    """Tests for _build_claude_fix_prompt."""

    def test_prompt_contains_task_ref(self):
        prompt = _build_claude_fix_prompt("myproject#5")
        assert "myproject#5" in prompt
        assert "CRITICAL" in prompt
        assert "HIGH" in prompt
        assert "НЕ делай коммит" in prompt


class TestRunCodexReview:
    """Tests for run_codex_review."""

    @patch("ralph_cli.commands.implement.shutil.which", return_value=None)
    def test_codex_not_found(self, mock_which, temp_dir, settings):
        log_path = temp_dir / "review.log"
        success, is_lgtm = run_codex_review("proj#1", temp_dir, log_path, 1, settings)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_codex_success_with_lgtm(self, mock_popen, mock_which, temp_dir, settings):
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter(
            [
                b"user\n",
                b"prompt text with LGTM instruction\n",
                b"thinking\n",
                b"codex\n",
                b"Review complete. LGTM\n",
            ]
        )
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        success, is_lgtm = run_codex_review("proj#1", temp_dir, log_path, 1, settings)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_codex_success_without_lgtm(self, mock_popen, mock_which, temp_dir, settings):
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter(
            [
                b"thinking\n",
                b"Found 2 CRITICAL issues\n",
            ]
        )
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        success, is_lgtm = run_codex_review("proj#1", temp_dir, log_path, 1, settings)
        assert success is True
        assert is_lgtm is False

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_lgtm_in_prompt_not_detected(self, mock_popen, mock_which, temp_dir, settings):
        """LGTM in prompt (before first 'thinking') must not trigger is_lgtm."""
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter(
            [
                b"user\n",
                b'If no issues write "LGTM"\n',
                b"thinking\n",
                b"codex\n",
                b"Found 1 MEDIUM issue\n",
            ]
        )
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        success, is_lgtm = run_codex_review("proj#1", temp_dir, log_path, 1, settings)
        assert success is True
        assert is_lgtm is False

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_codex_failure(self, mock_popen, mock_which, temp_dir, settings):
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"thinking\n", b"Error occurred\n"])
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        success, is_lgtm = run_codex_review("proj#1", temp_dir, log_path, 1, settings)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_first_iteration_no_uncommitted_flag(self, mock_popen, mock_which, temp_dir, settings):
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"thinking\n", b"LGTM\n"])
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_codex_review("proj#1", temp_dir, log_path, 1, settings)

        cmd = mock_popen.call_args[0][0]
        assert "--uncommitted" not in cmd

    @patch("ralph_cli.commands.implement.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.implement.subprocess.Popen")
    def test_subsequent_iteration_has_uncommitted_flag(
        self, mock_popen, mock_which, temp_dir, settings
    ):
        log_path = temp_dir / "review.log"

        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"thinking\n", b"LGTM\n"])
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_codex_review("proj#1", temp_dir, log_path, 2, settings)

        cmd = mock_popen.call_args[0][0]
        assert "--uncommitted" in cmd


class TestRunCodexReviewLoop:
    """Tests for run_codex_review_loop."""

    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_lgtm_first_iteration(self, mock_review, temp_dir, settings, session_log):
        mock_review.return_value = (True, True)

        result = run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
        assert result is True
        assert mock_review.call_count == 1
        session_log.append.assert_any_call("Codex LGTM after 1 iteration(s)")

    @patch("ralph_cli.commands.implement._create_fixup_commit")
    @patch("ralph_cli.commands.implement.run_claude_fix")
    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_lgtm_second_iteration(
        self, mock_review, mock_fix, mock_fixup, temp_dir, settings, session_log
    ):
        mock_review.side_effect = [(True, False), (True, True)]
        mock_fix.return_value = True

        result = run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
        assert result is True
        assert mock_review.call_count == 2
        assert mock_fix.call_count == 1
        mock_fixup.assert_called_once()
        session_log.append.assert_any_call("Codex LGTM after 2 iteration(s)")

    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_review_failure_stops_loop(self, mock_review, temp_dir, settings, session_log):
        mock_review.return_value = (False, False)

        result = run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
        assert result is False
        assert mock_review.call_count == 1
        session_log.append.assert_any_call("Codex review failed at iteration 1")

    @patch("ralph_cli.commands.implement.run_claude_fix")
    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_fix_failure_stops_loop(self, mock_review, mock_fix, temp_dir, settings, session_log):
        mock_review.return_value = (True, False)
        mock_fix.return_value = False

        result = run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
        assert result is False
        assert mock_fix.call_count == 1
        session_log.append.assert_any_call("Claude fix failed at iteration 1")

    @patch("ralph_cli.commands.implement._create_fixup_commit")
    @patch("ralph_cli.commands.implement.run_claude_fix")
    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_max_iterations_reached(
        self, mock_review, mock_fix, mock_fixup, temp_dir, settings, session_log
    ):
        mock_review.return_value = (True, False)
        mock_fix.return_value = True

        result = run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
        assert result is False
        assert mock_review.call_count == 3
        # Fix only called on iterations 1 and 2 (not last)
        assert mock_fix.call_count == 2
        session_log.append.assert_any_call("Codex review: max iterations (3) reached without LGTM")

    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_no_fixup_on_first_iteration_lgtm(self, mock_review, temp_dir, settings, session_log):
        """No fixup commit needed when LGTM on first try (no fixes were made)."""
        mock_review.return_value = (True, True)

        with patch("ralph_cli.commands.implement._create_fixup_commit") as mock_fixup:
            run_codex_review_loop("proj#1", temp_dir, temp_dir, settings, session_log)
            mock_fixup.assert_not_called()

    @patch("ralph_cli.commands.implement._create_fixup_commit")
    @patch("ralph_cli.commands.implement.run_claude_fix")
    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_session_id_passed_to_fix(
        self, mock_review, mock_fix, mock_fixup, temp_dir, settings, session_log
    ):
        """Session ID from main implementation should be passed to claude fix."""
        mock_review.side_effect = [(True, False), (True, True)]
        mock_fix.return_value = True

        run_codex_review_loop(
            "proj#1",
            temp_dir,
            temp_dir,
            settings,
            session_log,
            session_id="abc12345",
        )

        # Verify session_id was passed to run_claude_fix
        fix_call = mock_fix.call_args
        assert fix_call.kwargs.get("resume_session") == "abc12345"

    @patch("ralph_cli.commands.implement._create_fixup_commit")
    @patch("ralph_cli.commands.implement.run_claude_fix")
    @patch("ralph_cli.commands.implement.run_codex_review")
    def test_no_session_id_works(
        self, mock_review, mock_fix, mock_fixup, temp_dir, settings, session_log
    ):
        """Loop works without session_id (None passed to fix)."""
        mock_review.side_effect = [(True, False), (True, True)]
        mock_fix.return_value = True

        run_codex_review_loop(
            "proj#1",
            temp_dir,
            temp_dir,
            settings,
            session_log,
        )

        fix_call = mock_fix.call_args
        assert fix_call.kwargs.get("resume_session") is None


class TestRunClaudeFix:
    """Tests for run_claude_fix."""

    @patch("ralph_cli.commands.implement.run_claude")
    def test_passes_resume_session(self, mock_run_claude, temp_dir, settings):
        """Verify resume_session is forwarded to run_claude."""
        mock_run_claude.return_value = MagicMock(
            error_type=MagicMock(is_success=True),
            duration_seconds=30,
            cost_usd=0.05,
        )

        run_claude_fix(
            "proj#1",
            temp_dir,
            temp_dir / "fix.log",
            1,
            settings,
            resume_session="abc12345",
        )

        call_kwargs = mock_run_claude.call_args.kwargs
        assert call_kwargs["resume_session"] == "abc12345"

    @patch("ralph_cli.commands.implement.run_claude")
    def test_no_resume_session(self, mock_run_claude, temp_dir, settings):
        """Without resume_session, run_claude gets None."""
        mock_run_claude.return_value = MagicMock(
            error_type=MagicMock(is_success=True),
            duration_seconds=30,
            cost_usd=0.05,
        )

        run_claude_fix(
            "proj#1",
            temp_dir,
            temp_dir / "fix.log",
            1,
            settings,
        )

        call_kwargs = mock_run_claude.call_args.kwargs
        assert call_kwargs.get("resume_session") is None

    @patch("ralph_cli.commands.implement.run_claude")
    def test_no_model_override_on_resume(self, mock_run_claude, temp_dir, settings):
        """When resuming, model should not be overridden (uses original session's model)."""
        mock_run_claude.return_value = MagicMock(
            error_type=MagicMock(is_success=True),
            duration_seconds=30,
            cost_usd=0.05,
        )

        run_claude_fix(
            "proj#1",
            temp_dir,
            temp_dir / "fix.log",
            1,
            settings,
            resume_session="abc12345",
        )

        call_kwargs = mock_run_claude.call_args.kwargs
        # Should not force a different model when resuming
        assert "model" not in call_kwargs or call_kwargs["model"] == "opus"


class TestCreateFixupCommit:
    """Tests for _create_fixup_commit."""

    @patch("ralph_cli.commands.implement.subprocess.run")
    def test_no_changes_skips(self, mock_run, temp_dir, session_log):
        # git status returns empty (no changes)
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        _create_fixup_commit("proj#1", temp_dir, session_log)

        # Only git status should be called
        assert mock_run.call_count == 1
        session_log.append.assert_not_called()

    @patch("ralph_cli.commands.implement.subprocess.run")
    def test_creates_fixup_when_changes(self, mock_run, temp_dir, session_log):
        # First call: git status --porcelain (has changes)
        # Second call: git log -1 (last commit hash)
        # Third call: git add -A
        # Fourth call: git commit --fixup
        # Fifth call: git rebase
        mock_run.side_effect = [
            MagicMock(stdout=" M file.py\n", returncode=0),
            MagicMock(stdout="abc123def456\n", returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]

        _create_fixup_commit("proj#1", temp_dir, session_log)

        assert mock_run.call_count == 5
        session_log.append.assert_called_once_with("Created fixup commit for codex review fixes")

    @patch("ralph_cli.commands.implement.subprocess.run")
    def test_no_commit_hash_skips(self, mock_run, temp_dir, session_log):
        mock_run.side_effect = [
            MagicMock(stdout=" M file.py\n", returncode=0),
            MagicMock(stdout="", returncode=0),  # empty hash
        ]

        _create_fixup_commit("proj#1", temp_dir, session_log)

        assert mock_run.call_count == 2
        session_log.append.assert_not_called()


class TestConfigCodexSettings:
    """Tests for codex review settings in config."""

    def test_defaults(self):
        settings = Settings(_env_file=None)
        assert settings.codex_review_max_iterations == 3
        assert settings.codex_review_model == "gpt-5.3-codex"

    def test_custom_values(self):
        settings = Settings(
            _env_file=None,
            codex_review_max_iterations=5,
            codex_review_model="gpt-4o",
        )
        assert settings.codex_review_max_iterations == 5
        assert settings.codex_review_model == "gpt-4o"

    def test_from_env_vars(self, monkeypatch):
        monkeypatch.setenv("CODEX_REVIEW_MAX_ITERATIONS", "2")
        settings = Settings(_env_file=None)
        assert settings.codex_review_max_iterations == 2
