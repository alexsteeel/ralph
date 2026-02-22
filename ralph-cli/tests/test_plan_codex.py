"""Tests for Codex plan review in plan command."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from ralph_cli.commands.plan import (
    _check_plan_lgtm,
    run_codex_plan_review,
)
from ralph_cli.config import Settings
from ralph_cli.prompts import load_prompt


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        _env_file=None,
        codex_plan_review_enabled=True,
        codex_review_model="gpt-5.3-codex",
    )


@pytest.fixture
def session_log():
    """Create mock session log."""
    return MagicMock()


# ---------------------------------------------------------------------------
# codex-plan-reviewer prompt template
# ---------------------------------------------------------------------------


class TestCodexPlanReviewerPrompt:
    def test_contains_project_and_task(self):
        prompt = load_prompt("codex-plan-reviewer", project="myproj", number="42")
        assert "myproj" in prompt
        assert "42" in prompt

    def test_no_unreplaced_placeholders(self):
        prompt = load_prompt("codex-plan-reviewer", project="myproj", number="42")
        assert "{project}" not in prompt
        assert "{number}" not in prompt

    @pytest.mark.parametrize(
        "expected",
        [
            "add_review_finding",
            'review_type="plan"',
            'author="codex-plan-reviewer"',
            "tasks(",
            "Do NOT modify any files",
        ],
    )
    def test_prompt_contains(self, expected):
        prompt = load_prompt("codex-plan-reviewer", project="proj", number="1")
        assert expected in prompt


# ---------------------------------------------------------------------------
# _check_plan_lgtm
# ---------------------------------------------------------------------------


class TestCheckPlanLgtm:
    @patch("ralph_tasks.core.list_review_findings")
    def test_lgtm_no_findings(self, mock_findings):
        mock_findings.return_value = []
        is_lgtm, count = _check_plan_lgtm("proj", 1)
        assert is_lgtm is True
        assert count == 0
        mock_findings.assert_called_once_with("proj", 1, review_type="plan", status="open")

    @patch("ralph_tasks.core.list_review_findings")
    def test_not_lgtm_with_findings(self, mock_findings):
        mock_findings.return_value = [
            {"text": "issue 1", "status": "open"},
            {"text": "issue 2", "status": "open"},
        ]
        is_lgtm, count = _check_plan_lgtm("proj", 1)
        assert is_lgtm is False
        assert count == 2

    def test_returns_true_on_exception(self):
        """On Neo4j failure, treat as LGTM to avoid blocking pipeline."""
        with patch(
            "ralph_tasks.core.list_review_findings",
            side_effect=Exception("neo4j down"),
        ):
            is_lgtm, count = _check_plan_lgtm("proj", 1)
            assert is_lgtm is True
            assert count == 0


# ---------------------------------------------------------------------------
# run_codex_plan_review
# ---------------------------------------------------------------------------


class TestRunCodexPlanReview:
    def _make_kwargs(self, settings, session_log, temp_dir):
        log_dir = temp_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        return {
            "task_ref": "proj#1",
            "project": "proj",
            "task_number": 1,
            "working_dir": temp_dir,
            "log_dir": log_dir,
            "settings": settings,
            "session_log": session_log,
        }

    def test_disabled_returns_true_true(self, temp_dir, session_log):
        settings = Settings(_env_file=None, codex_plan_review_enabled=False)
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True
        session_log.append.assert_called_once_with("Codex plan review: disabled")

    @patch("ralph_cli.commands.plan.shutil.which", return_value=None)
    def test_codex_not_found_graceful_skip(self, mock_which, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.plan.load_prompt", side_effect=FileNotFoundError("not found"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_missing_prompt_file_graceful_skip(
        self, mock_which, mock_load, temp_dir, settings, session_log
    ):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.plan.load_prompt", side_effect=KeyError("number"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_key_error_in_prompt_graceful_skip(
        self, mock_which, mock_load, temp_dir, settings, session_log
    ):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_success_lgtm(self, mock_which, mock_run, mock_lgtm, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(False, 3))
    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_success_with_issues(
        self, mock_which, mock_run, mock_lgtm, temp_dir, settings, session_log
    ):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=1))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_codex_failure_exit_code(self, mock_which, mock_run, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan.subprocess.run", side_effect=OSError("spawn failed"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_exception_returns_false(self, mock_which, mock_run, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_launches_interactive_codex(
        self, mock_which, mock_run, mock_lgtm, temp_dir, settings, session_log
    ):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        run_codex_plan_review(**kwargs)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"
        # Interactive mode: no "exec", no "--full-auto"
        assert "exec" not in cmd
        assert "--full-auto" not in cmd
        # Prompt is the last argument
        assert "proj" in cmd[-1]


# ---------------------------------------------------------------------------
# Config: codex_plan_review_enabled
# ---------------------------------------------------------------------------


class TestConfigCodexPlanReview:
    def test_default_enabled(self):
        s = Settings(_env_file=None)
        assert s.codex_plan_review_enabled is True

    def test_can_disable(self):
        s = Settings(_env_file=None, codex_plan_review_enabled=False)
        assert s.codex_plan_review_enabled is False
