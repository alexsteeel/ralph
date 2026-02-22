"""Tests for Codex plan review in plan command."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from ralph_cli.commands.plan import (
    _build_codex_plan_prompt,
    _check_plan_lgtm,
    run_codex_plan_review,
)
from ralph_cli.config import Settings


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
# _build_codex_plan_prompt
# ---------------------------------------------------------------------------


class TestBuildCodexPlanPrompt:
    def test_contains_project_and_task(self):
        prompt = _build_codex_plan_prompt("myproj", 42)
        assert "myproj" in prompt
        assert "42" in prompt

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
        prompt = _build_codex_plan_prompt("proj", 1)
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

    @staticmethod
    def _make_mock_proc(stdout_lines, returncode=0):
        proc = MagicMock()
        proc.stdout = iter(stdout_lines)
        proc.returncode = returncode
        proc.wait.return_value = returncode
        return proc

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

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_success_lgtm(self, mock_which, mock_popen, mock_lgtm, temp_dir, settings, session_log):
        mock_popen.return_value = self._make_mock_proc([b"thinking\n", b"No issues found\n"])

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(False, 3))
    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_success_with_issues(
        self, mock_which, mock_popen, mock_lgtm, temp_dir, settings, session_log
    ):
        mock_popen.return_value = self._make_mock_proc([b"thinking\n", b"Found 3 issues\n"])

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_codex_failure_exit_code(self, mock_which, mock_popen, temp_dir, settings, session_log):
        mock_popen.return_value = self._make_mock_proc([b"error\n"], returncode=1)

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan.subprocess.Popen", side_effect=OSError("spawn failed"))
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_exception_returns_false(self, mock_which, mock_popen, temp_dir, settings, session_log):
        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is False
        assert is_lgtm is False

    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_timeout_kills_process(self, mock_which, mock_popen, temp_dir, settings, session_log):
        proc = self._make_mock_proc([b"slow\n"])
        # First call (with timeout) raises; second call (after kill) succeeds
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="codex", timeout=1800),
            None,
        ]
        proc.kill.return_value = None
        mock_popen.return_value = proc

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is False
        assert is_lgtm is False
        proc.kill.assert_called_once()

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_uses_codex_review_model(
        self, mock_which, mock_popen, mock_lgtm, temp_dir, session_log
    ):
        settings = Settings(
            _env_file=None,
            codex_plan_review_enabled=True,
            codex_review_model="gpt-4o",
        )
        mock_popen.return_value = self._make_mock_proc([b"ok\n"])

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        run_codex_plan_review(**kwargs)

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--full-auto" in cmd
        assert any("gpt-4o" in arg for arg in cmd)

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_creates_log_file(
        self, mock_which, mock_popen, mock_lgtm, temp_dir, settings, session_log
    ):
        mock_popen.return_value = self._make_mock_proc([b"output line\n"])

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        run_codex_plan_review(**kwargs)

        log_files = list(kwargs["log_dir"].glob("*plan_review*"))
        assert len(log_files) == 1

    @patch("ralph_cli.commands.plan._check_plan_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.plan.subprocess.Popen")
    @patch("ralph_cli.commands.plan.shutil.which", return_value="/usr/bin/codex")
    def test_streams_tool_events(
        self, mock_which, mock_popen, mock_lgtm, temp_dir, settings, session_log
    ):
        mock_popen.return_value = self._make_mock_proc(
            [
                b"some output\n",
                b"tool call: add_review_finding\n",
                b"normal line\n",
            ]
        )

        kwargs = self._make_kwargs(settings, session_log, temp_dir)
        success, is_lgtm = run_codex_plan_review(**kwargs)
        assert success is True
        assert is_lgtm is True
        assert session_log.append.call_count >= 2


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
