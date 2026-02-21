"""Tests for review chain orchestration."""

from unittest.mock import MagicMock, patch

import pytest
from ralph_cli.commands.review_chain import (
    CODE_REVIEW_AGENTS,
    CODE_REVIEW_SECTION_TYPES,
    ReviewChainContext,
    ReviewPhaseResult,
    _parse_task_ref,
    check_lgtm,
    create_fixup_commit,
    run_code_review_phase,
    run_codex_review_phase,
    run_finalization_phase,
    run_parallel_code_reviews,
    run_review_chain,
    run_security_review_phase,
    run_simplifier_phase,
    run_single_review_agent,
)
from ralph_cli.config import Settings


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        _env_file=None,
        claude_review_model="sonnet",
        code_review_max_iterations=3,
        security_review_max_iterations=2,
        codex_review_max_iterations=2,
    )


@pytest.fixture
def session_log():
    """Create mock session log."""
    log = MagicMock()
    log.append = MagicMock()
    return log


@pytest.fixture
def notifier():
    """Create mock notifier."""
    n = MagicMock()
    n.review_failed = MagicMock()
    return n


@pytest.fixture
def ctx(temp_dir, settings, session_log, notifier):
    """Create test ReviewChainContext."""
    log_dir = temp_dir / "logs"
    log_dir.mkdir()
    return ReviewChainContext(
        task_ref="proj#1",
        project="proj",
        task_number=1,
        working_dir=temp_dir,
        log_dir=log_dir,
        settings=settings,
        session_log=session_log,
        notifier=notifier,
        main_session_id="main-session-123",
        base_commit="abc123def456",
    )


def _make_result(success=True, cost=0.05, duration=30, session_id="sess-1"):
    """Helper to create mock TaskResult."""
    result = MagicMock()
    result.error_type = MagicMock()
    result.error_type.is_success = success
    result.error_type.value = "COMPLETED" if success else "UNKNOWN"
    result.cost_usd = cost
    result.duration_seconds = duration
    result.session_id = session_id
    return result


# ---------------------------------------------------------------------------
# _parse_task_ref
# ---------------------------------------------------------------------------


class TestParseTaskRef:
    def test_basic(self):
        assert _parse_task_ref("proj#1") == ("proj", 1)

    def test_multi_digit(self):
        assert _parse_task_ref("my-project#123") == ("my-project", 123)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_task_ref("no-hash")


# ---------------------------------------------------------------------------
# check_lgtm
# ---------------------------------------------------------------------------


class TestCheckLgtm:
    @patch("ralph_tasks.core.list_review_findings")
    def test_lgtm_when_no_open_findings(self, mock_findings):
        mock_findings.return_value = []
        is_lgtm, count = check_lgtm("proj", 1, ["code-review"])
        assert is_lgtm is True
        assert count == 0

    @patch("ralph_tasks.core.list_review_findings")
    def test_not_lgtm_when_open_findings(self, mock_findings):
        mock_findings.return_value = [
            {"section_type": "code-review", "status": "open"},
            {"section_type": "code-review", "status": "open"},
        ]
        is_lgtm, count = check_lgtm("proj", 1, ["code-review"])
        assert is_lgtm is False
        assert count == 2

    @patch("ralph_tasks.core.list_review_findings")
    def test_filters_by_section_type(self, mock_findings):
        mock_findings.return_value = [
            {"section_type": "security-review", "status": "open"},
            {"section_type": "code-review", "status": "open"},
        ]
        is_lgtm, count = check_lgtm("proj", 1, ["code-review"])
        assert is_lgtm is False
        assert count == 1

    def test_returns_false_on_import_error(self):
        """When ralph_tasks is not available, returns (False, -1)."""
        with patch(
            "ralph_tasks.core.list_review_findings",
            side_effect=Exception("not available"),
        ):
            is_lgtm, count = check_lgtm("proj", 1, ["code-review"])
            assert is_lgtm is False
            assert count == -1


# ---------------------------------------------------------------------------
# create_fixup_commit
# ---------------------------------------------------------------------------


class TestCreateFixupCommit:
    @patch("ralph_cli.commands.review_chain.subprocess.run")
    def test_no_changes_skips(self, mock_run, temp_dir, session_log):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        create_fixup_commit(temp_dir, session_log)
        assert mock_run.call_count == 1
        session_log.append.assert_not_called()

    @patch("ralph_cli.commands.review_chain.subprocess.run")
    def test_creates_fixup_when_changes(self, mock_run, temp_dir, session_log):
        mock_run.side_effect = [
            MagicMock(stdout=" M file.py\n", returncode=0),  # status
            MagicMock(stdout="abc123\n", returncode=0),  # log
            MagicMock(returncode=0),  # add
            MagicMock(returncode=0),  # commit
            MagicMock(returncode=0),  # rebase
        ]
        create_fixup_commit(temp_dir, session_log, "test fixes")
        assert mock_run.call_count == 5
        session_log.append.assert_called_once_with("Created fixup commit for test fixes")

    @patch("ralph_cli.commands.review_chain.subprocess.run")
    def test_no_commit_hash_skips(self, mock_run, temp_dir, session_log):
        mock_run.side_effect = [
            MagicMock(stdout=" M file.py\n", returncode=0),
            MagicMock(stdout="", returncode=0),  # empty hash
        ]
        create_fixup_commit(temp_dir, session_log)
        assert mock_run.call_count == 2
        session_log.append.assert_not_called()


# ---------------------------------------------------------------------------
# run_single_review_agent
# ---------------------------------------------------------------------------


class TestRunSingleReviewAgent:
    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_success(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=True, session_id="rev-1")
        success, sid = run_single_review_agent(ctx, "code-reviewer", "code-review")
        assert success is True
        assert sid == "rev-1"

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_failure(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=False, session_id="rev-2")
        success, sid = run_single_review_agent(ctx, "code-reviewer", "code-review")
        assert success is False
        assert sid == "rev-2"

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_missing_prompt(self, mock_run_claude, ctx):
        with patch(
            "ralph_cli.commands.review_chain.load_prompt",
            side_effect=FileNotFoundError("not found"),
        ):
            success, sid = run_single_review_agent(ctx, "nonexistent", "none", "x")
            assert success is False
            assert sid is None
            mock_run_claude.assert_not_called()

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_uses_review_model(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result()
        run_single_review_agent(ctx, "code-reviewer", "code-review")
        call_kwargs = mock_run_claude.call_args.kwargs
        assert call_kwargs["model"] == "sonnet"

    @patch("ralph_cli.commands.review_chain.run_claude")
    @patch("ralph_cli.commands.review_chain.load_prompt")
    def test_passes_context_to_prompt(self, mock_load, mock_run_claude, ctx):
        mock_load.return_value = "prompt text"
        mock_run_claude.return_value = _make_result()
        run_single_review_agent(ctx, "code-reviewer", "code-review", "code-reviewer")
        mock_load.assert_called_once_with(
            "review-agent",
            task_ref="proj#1",
            project="proj",
            number="1",
            base_commit="abc123def456",
            review_type="code-review",
            author="code-reviewer",
        )


# ---------------------------------------------------------------------------
# run_parallel_code_reviews
# ---------------------------------------------------------------------------


class TestRunParallelCodeReviews:
    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_all_succeed(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=True)
        results = run_parallel_code_reviews(ctx)
        assert len(results) == 4
        assert all(success for success, _ in results.values())

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_stores_session_ids(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=True, session_id="s1")
        run_parallel_code_reviews(ctx)
        # All 4 agents should have session IDs stored
        assert len(ctx.review_session_ids) == 4


# ---------------------------------------------------------------------------
# run_code_review_phase
# ---------------------------------------------------------------------------


class TestRunCodeReviewPhase:
    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.review_chain.run_parallel_code_reviews")
    def test_lgtm_first_iteration(self, mock_parallel, mock_lgtm, ctx):
        mock_parallel.return_value = {
            "code-reviewer": (True, "s1"),
            "comment-analyzer": (True, "s2"),
            "pr-test-analyzer": (True, "s3"),
            "silent-failure-hunter": (True, "s4"),
        }
        result = run_code_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True

    @patch("ralph_cli.commands.review_chain.run_parallel_code_reviews")
    def test_all_agents_fail(self, mock_parallel, ctx):
        mock_parallel.return_value = {
            "code-reviewer": (False, None),
            "comment-analyzer": (False, None),
            "pr-test-analyzer": (False, None),
            "silent-failure-hunter": (False, None),
        }
        result = run_code_review_phase(ctx)
        assert result.success is False
        assert "All review agents failed" in result.error

    @patch("ralph_cli.commands.review_chain.create_fixup_commit")
    @patch("ralph_cli.commands.review_chain._resume_reviewers")
    @patch("ralph_cli.commands.review_chain.run_fix_session", return_value=True)
    @patch("ralph_cli.commands.review_chain.check_lgtm")
    @patch("ralph_cli.commands.review_chain.run_parallel_code_reviews")
    def test_lgtm_after_fix(self, mock_parallel, mock_lgtm, mock_fix, mock_resume, mock_fixup, ctx):
        mock_parallel.return_value = {"code-reviewer": (True, "s1")}
        # First check: not LGTM; after fix: LGTM
        mock_lgtm.side_effect = [(False, 2), (True, 0)]
        result = run_code_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True
        mock_fix.assert_called_once()

    @patch("ralph_cli.commands.review_chain.create_fixup_commit")
    @patch("ralph_cli.commands.review_chain._resume_reviewers")
    @patch("ralph_cli.commands.review_chain.run_fix_session", return_value=True)
    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(False, 3))
    @patch("ralph_cli.commands.review_chain.run_parallel_code_reviews")
    def test_max_iterations(self, mock_parallel, mock_lgtm, mock_fix, mock_resume, mock_fixup, ctx):
        mock_parallel.return_value = {"code-reviewer": (True, "s1")}
        result = run_code_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is False
        assert result.findings_count == 3

    @patch("ralph_cli.commands.review_chain.run_fix_session", return_value=False)
    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(False, 1))
    @patch("ralph_cli.commands.review_chain.run_parallel_code_reviews")
    def test_fix_failure_stops(self, mock_parallel, mock_lgtm, mock_fix, ctx):
        mock_parallel.return_value = {"code-reviewer": (True, "s1")}
        result = run_code_review_phase(ctx)
        assert result.success is False
        assert "Fix session failed" in result.error


# ---------------------------------------------------------------------------
# run_simplifier_phase
# ---------------------------------------------------------------------------


class TestRunSimplifierPhase:
    @patch("ralph_cli.commands.review_chain.create_fixup_commit")
    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_success(self, mock_run_claude, mock_fixup, ctx):
        mock_run_claude.return_value = _make_result(success=True, cost=0.10)
        result = run_simplifier_phase(ctx)
        assert result.success is True
        assert result.cost_usd == 0.10
        mock_fixup.assert_called_once()

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_failure(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=False)
        result = run_simplifier_phase(ctx)
        assert result.success is False

    def test_missing_prompt_skips(self, ctx):
        with patch(
            "ralph_cli.commands.review_chain.load_prompt",
            side_effect=FileNotFoundError("not found"),
        ):
            result = run_simplifier_phase(ctx)
            assert result.success is True
            assert result.error is not None


# ---------------------------------------------------------------------------
# run_security_review_phase
# ---------------------------------------------------------------------------


class TestRunSecurityReviewPhase:
    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.review_chain._run_agent_with_retry")
    def test_lgtm_first_check(self, mock_agent, mock_lgtm, ctx):
        mock_agent.return_value = (True, "sec-1")
        result = run_security_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True

    @patch("ralph_cli.commands.review_chain._run_agent_with_retry")
    def test_agent_failure(self, mock_agent, ctx):
        mock_agent.return_value = (False, None)
        result = run_security_review_phase(ctx)
        assert result.success is False

    @patch("ralph_cli.commands.review_chain.create_fixup_commit")
    @patch("ralph_cli.commands.review_chain.run_claude")
    @patch("ralph_cli.commands.review_chain.run_fix_session", return_value=True)
    @patch("ralph_cli.commands.review_chain.check_lgtm")
    @patch("ralph_cli.commands.review_chain._run_agent_with_retry")
    def test_lgtm_after_fix(self, mock_agent, mock_lgtm, mock_fix, mock_rereview, mock_fixup, ctx):
        mock_agent.return_value = (True, "sec-1")
        mock_lgtm.side_effect = [(False, 1), (True, 0)]
        mock_rereview.return_value = _make_result()
        result = run_security_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True


# ---------------------------------------------------------------------------
# run_codex_review_phase
# ---------------------------------------------------------------------------


class TestRunCodexReviewPhase:
    @patch("ralph_cli.commands.review_chain.shutil.which", return_value=None)
    def test_codex_not_found_skips(self, mock_which, ctx):
        result = run_codex_review_phase(ctx)
        assert result.success is True
        assert "not found" in result.error

    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.review_chain.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.review_chain.subprocess.Popen")
    def test_lgtm_first_iteration(self, mock_popen, mock_which, mock_lgtm, ctx):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"Review complete.\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        result = run_codex_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True
        mock_lgtm.assert_called_with(ctx.project, ctx.task_number, ["codex-review"])

    @patch("ralph_cli.commands.review_chain.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.review_chain.subprocess.Popen")
    def test_failure_exit_code(self, mock_popen, mock_which, ctx):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"thinking\n", b"Error\n"])
        mock_proc.returncode = 1
        mock_proc.wait.return_value = 1
        mock_popen.return_value = mock_proc

        result = run_codex_review_phase(ctx)
        assert result.success is False

    @patch("ralph_cli.commands.review_chain.check_lgtm", return_value=(True, 0))
    @patch("ralph_cli.commands.review_chain.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.review_chain.subprocess.Popen")
    def test_first_iteration_no_uncommitted(self, mock_popen, mock_which, mock_lgtm, ctx):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([b"Review complete.\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        run_codex_review_phase(ctx)
        cmd = mock_popen.call_args[0][0]
        assert "--uncommitted" not in cmd

    @patch("ralph_cli.commands.review_chain.create_fixup_commit")
    @patch("ralph_cli.commands.review_chain.run_fix_session", return_value=True)
    @patch("ralph_cli.commands.review_chain.check_lgtm")
    @patch("ralph_cli.commands.review_chain.shutil.which", return_value="/usr/bin/codex")
    @patch("ralph_cli.commands.review_chain.subprocess.Popen")
    def test_not_lgtm_triggers_fix(
        self, mock_popen, mock_which, mock_lgtm, mock_fix, mock_fixup, ctx
    ):
        """When Neo4j has open findings, fix session is triggered."""

        def make_proc():
            proc = MagicMock()
            proc.stdout = iter([b"Review output.\n"])
            proc.returncode = 0
            proc.wait.return_value = 0
            return proc

        mock_popen.side_effect = [make_proc(), make_proc()]

        # First check: not LGTM (2 findings), after fix: LGTM
        mock_lgtm.side_effect = [(False, 2), (True, 0)]

        result = run_codex_review_phase(ctx)
        assert result.success is True
        assert result.lgtm is True
        mock_fix.assert_called_once()


# ---------------------------------------------------------------------------
# run_finalization_phase
# ---------------------------------------------------------------------------


class TestRunFinalizationPhase:
    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_success(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=True, cost=0.20)
        result = run_finalization_phase(ctx)
        assert result.success is True
        assert result.cost_usd == 0.20

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_resumes_main_session(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result()
        run_finalization_phase(ctx)
        call_kwargs = mock_run_claude.call_args.kwargs
        assert call_kwargs["resume_session"] == "main-session-123"

    @patch("ralph_cli.commands.review_chain.run_claude")
    def test_failure(self, mock_run_claude, ctx):
        mock_run_claude.return_value = _make_result(success=False)
        result = run_finalization_phase(ctx)
        assert result.success is False

    def test_missing_prompt(self, ctx):
        with patch(
            "ralph_cli.commands.review_chain.load_prompt",
            side_effect=FileNotFoundError("not found"),
        ):
            result = run_finalization_phase(ctx)
            assert result.success is False


# ---------------------------------------------------------------------------
# run_review_chain (integration)
# ---------------------------------------------------------------------------


class TestRunReviewChain:
    @patch("ralph_cli.commands.review_chain.run_finalization_phase")
    @patch("ralph_cli.commands.review_chain.run_codex_review_phase")
    @patch("ralph_cli.commands.review_chain.run_security_review_phase")
    @patch("ralph_cli.commands.review_chain.run_simplifier_phase")
    @patch("ralph_cli.commands.review_chain.run_code_review_phase")
    def test_all_phases_succeed(
        self,
        mock_code,
        mock_simp,
        mock_sec,
        mock_codex,
        mock_final,
        temp_dir,
        settings,
        session_log,
    ):
        for mock in [mock_code, mock_simp, mock_sec, mock_codex, mock_final]:
            mock.return_value = ReviewPhaseResult(success=True, lgtm=True)

        result = run_review_chain(
            task_ref="proj#1",
            working_dir=temp_dir,
            log_dir=temp_dir,
            settings=settings,
            session_log=session_log,
        )
        assert result is True
        # All phases called
        mock_code.assert_called_once()
        mock_simp.assert_called_once()
        mock_sec.assert_called_once()
        mock_codex.assert_called_once()
        mock_final.assert_called_once()

    @patch("ralph_cli.commands.review_chain.run_finalization_phase")
    @patch("ralph_cli.commands.review_chain.run_codex_review_phase")
    @patch("ralph_cli.commands.review_chain.run_security_review_phase")
    @patch("ralph_cli.commands.review_chain.run_simplifier_phase")
    @patch("ralph_cli.commands.review_chain.run_code_review_phase")
    def test_finalization_failure_returns_false(
        self,
        mock_code,
        mock_simp,
        mock_sec,
        mock_codex,
        mock_final,
        temp_dir,
        settings,
        session_log,
    ):
        for mock in [mock_code, mock_simp, mock_sec, mock_codex]:
            mock.return_value = ReviewPhaseResult(success=True, lgtm=True)
        mock_final.return_value = ReviewPhaseResult(success=False, error="failed")

        result = run_review_chain(
            task_ref="proj#1",
            working_dir=temp_dir,
            log_dir=temp_dir,
            settings=settings,
            session_log=session_log,
        )
        assert result is False

    @patch("ralph_cli.commands.review_chain.run_finalization_phase")
    @patch("ralph_cli.commands.review_chain.run_codex_review_phase")
    @patch("ralph_cli.commands.review_chain.run_security_review_phase")
    @patch("ralph_cli.commands.review_chain.run_simplifier_phase")
    @patch("ralph_cli.commands.review_chain.run_code_review_phase")
    def test_notifier_called_on_failure(
        self,
        mock_code,
        mock_simp,
        mock_sec,
        mock_codex,
        mock_final,
        temp_dir,
        settings,
        session_log,
        notifier,
    ):
        mock_code.return_value = ReviewPhaseResult(success=False, error="agents failed")
        mock_simp.return_value = ReviewPhaseResult(success=True)
        mock_sec.return_value = ReviewPhaseResult(success=True, lgtm=True)
        mock_codex.return_value = ReviewPhaseResult(success=True, lgtm=True)
        mock_final.return_value = ReviewPhaseResult(success=True)

        run_review_chain(
            task_ref="proj#1",
            working_dir=temp_dir,
            log_dir=temp_dir,
            settings=settings,
            session_log=session_log,
            notifier=notifier,
        )
        notifier.review_failed.assert_called_once()

    @patch("ralph_cli.commands.review_chain.run_finalization_phase")
    @patch("ralph_cli.commands.review_chain.run_codex_review_phase")
    @patch("ralph_cli.commands.review_chain.run_security_review_phase")
    @patch("ralph_cli.commands.review_chain.run_simplifier_phase")
    @patch("ralph_cli.commands.review_chain.run_code_review_phase")
    def test_base_commit_passed_to_context(
        self,
        mock_code,
        mock_simp,
        mock_sec,
        mock_codex,
        mock_final,
        temp_dir,
        settings,
        session_log,
    ):
        for mock in [mock_code, mock_simp, mock_sec, mock_codex, mock_final]:
            mock.return_value = ReviewPhaseResult(success=True, lgtm=True)

        run_review_chain(
            task_ref="proj#1",
            working_dir=temp_dir,
            log_dir=temp_dir,
            settings=settings,
            session_log=session_log,
            base_commit="abc123",
        )
        # Verify context passed to first phase has base_commit
        ctx = mock_code.call_args[0][0]
        assert ctx.base_commit == "abc123"

    @patch("ralph_cli.commands.review_chain.run_finalization_phase")
    @patch("ralph_cli.commands.review_chain.run_codex_review_phase")
    @patch("ralph_cli.commands.review_chain.run_security_review_phase")
    @patch("ralph_cli.commands.review_chain.run_simplifier_phase")
    @patch("ralph_cli.commands.review_chain.run_code_review_phase")
    def test_creates_reviews_log_dir(
        self,
        mock_code,
        mock_simp,
        mock_sec,
        mock_codex,
        mock_final,
        temp_dir,
        settings,
        session_log,
    ):
        for mock in [mock_code, mock_simp, mock_sec, mock_codex, mock_final]:
            mock.return_value = ReviewPhaseResult(success=True, lgtm=True)

        run_review_chain(
            task_ref="proj#1",
            working_dir=temp_dir,
            log_dir=temp_dir,
            settings=settings,
            session_log=session_log,
        )
        assert (temp_dir / "reviews").is_dir()


# ---------------------------------------------------------------------------
# Config settings
# ---------------------------------------------------------------------------


class TestConfigReviewSettings:
    def test_new_review_settings_defaults(self):
        s = Settings(_env_file=None)
        assert s.claude_review_model == "sonnet"
        assert s.code_review_max_iterations == 3
        assert s.security_review_max_iterations == 2

    def test_custom_values(self):
        s = Settings(
            _env_file=None,
            claude_review_model="haiku",
            code_review_max_iterations=5,
            security_review_max_iterations=4,
        )
        assert s.claude_review_model == "haiku"
        assert s.code_review_max_iterations == 5
        assert s.security_review_max_iterations == 4

    def test_codex_settings_still_work(self):
        s = Settings(_env_file=None)
        assert s.codex_review_max_iterations == 3
        assert s.codex_review_model == "gpt-5.3-codex"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_code_review_agents_count(self):
        assert len(CODE_REVIEW_AGENTS) == 4

    def test_section_types_match_agents(self):
        assert len(CODE_REVIEW_SECTION_TYPES) == 4
        for _, review_type, _ in CODE_REVIEW_AGENTS:
            assert review_type in CODE_REVIEW_SECTION_TYPES
