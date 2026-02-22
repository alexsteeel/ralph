"""Tests for Codex plan review in plan command."""

from unittest.mock import MagicMock, patch

import pytest
from ralph_cli.commands.plan import FlexibleConfirm, run_codex_plan_review
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
            "tasks(",
            "Do NOT modify any files",
            "LGTM",
        ],
    )
    def test_prompt_contains(self, expected):
        prompt = load_prompt("codex-plan-reviewer", project="proj", number="1")
        assert expected in prompt

    def test_no_add_review_finding(self):
        """Interactive prompt should NOT instruct to call add_review_finding."""
        prompt = load_prompt("codex-plan-reviewer", project="proj", number="1")
        assert "add_review_finding" not in prompt
        assert "update_task" not in prompt


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

    def test_disabled_returns_true(self, temp_dir, session_log):
        settings = Settings(_env_file=None, codex_plan_review_enabled=False)
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        assert run_codex_plan_review(**kwargs) is True
        session_log.append.assert_called_once_with("Codex plan review: disabled")

    @patch("ralph_cli.commands.plan.shutil.which", return_value=None)
    def test_codex_not_found_graceful_skip(self, mock_which, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        assert run_codex_plan_review(**kwargs) is True

    @patch("ralph_cli.commands.plan.load_prompt", side_effect=FileNotFoundError("not found"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_missing_prompt_file_graceful_skip(
        self, mock_which, mock_load, temp_dir, settings, session_log
    ):
        assert run_codex_plan_review(**self._make_kwargs(settings, session_log, temp_dir)) is True

    @patch("ralph_cli.commands.plan.load_prompt", side_effect=KeyError("number"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_key_error_in_prompt_graceful_skip(
        self, mock_which, mock_load, temp_dir, settings, session_log
    ):
        assert run_codex_plan_review(**self._make_kwargs(settings, session_log, temp_dir)) is True

    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_success(self, mock_which, mock_run, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        assert run_codex_plan_review(**kwargs) is True

    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=1))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_codex_failure_exit_code(self, mock_which, mock_run, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        assert run_codex_plan_review(**kwargs) is False

    @patch("ralph_cli.commands.plan.subprocess.run", side_effect=OSError("spawn failed"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_exception_returns_false(self, mock_which, mock_run, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        assert run_codex_plan_review(**kwargs) is False

    @patch("ralph_cli.commands.plan.subprocess.run", return_value=MagicMock(returncode=0))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_launches_interactive_codex(
        self, mock_which, mock_run, temp_dir, settings, session_log
    ):
        run_codex_plan_review(**self._make_kwargs(settings, session_log, temp_dir))

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"
        assert "exec" not in cmd
        assert "--full-auto" not in cmd
        assert "proj" in cmd[-1]


# ---------------------------------------------------------------------------
# Config: codex_plan_review_enabled
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FlexibleConfirm
# ---------------------------------------------------------------------------


class TestFlexibleConfirm:
    @pytest.mark.parametrize("value", ["y", "Y", "yes", "Yes", "YES", "да", "Да", "д", "1", "true"])
    def test_accepts_yes_variants(self, value):
        c = FlexibleConfirm("")
        assert c.process_response(value) is True

    @pytest.mark.parametrize("value", ["n", "N", "no", "No", "NO", "нет", "Нет", "н", "0", "false"])
    def test_accepts_no_variants(self, value):
        c = FlexibleConfirm("")
        assert c.process_response(value) is False

    def test_rejects_invalid(self):
        from rich.prompt import InvalidResponse

        c = FlexibleConfirm("")
        with pytest.raises(InvalidResponse):
            c.process_response("maybe")


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
