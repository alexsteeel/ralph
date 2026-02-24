"""Tests for MCP role separation: tool availability, field whitelists, review_type extraction."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from ralph_tasks.mcp.planner import _PLANNER_UPDATE_FIELDS
from ralph_tasks.mcp.planner import mcp as planner_mcp
from ralph_tasks.mcp.reviewer import _get_review_type
from ralph_tasks.mcp.reviewer import mcp as reviewer_mcp
from ralph_tasks.mcp.swe import _SWE_UPDATE_FIELDS
from ralph_tasks.mcp.swe import mcp as swe_mcp
from ralph_tasks.mcp.tools import _validate_source_path, update_task_impl


def _tool_names(mcp_instance) -> set[str]:
    """Extract registered tool names from a FastMCP instance."""
    return set(mcp_instance._tool_manager._tools.keys())


# ---------------------------------------------------------------------------
# Role tool separation tests (#1192, #1202)
# ---------------------------------------------------------------------------


class TestSweToolSet:
    """SWE role should have exactly the expected tools."""

    def test_has_task_crud(self):
        names = _tool_names(swe_mcp)
        assert "tasks" in names
        assert "create_task" in names
        assert "update_task" in names

    def test_has_review_read_reply_decline(self):
        names = _tool_names(swe_mcp)
        assert "list_review_findings" in names
        assert "reply_to_finding" in names
        assert "decline_finding" in names

    def test_cannot_add_or_resolve_findings(self):
        names = _tool_names(swe_mcp)
        assert "add_review_finding" not in names
        assert "resolve_finding" not in names

    def test_has_full_attachment_access(self):
        names = _tool_names(swe_mcp)
        assert "list_attachments" in names
        assert "add_attachment" in names
        assert "read_attachment" in names
        assert "delete_attachment" in names


class TestReviewerToolSet:
    """Reviewer role should have exactly the expected tools."""

    def test_has_read_only_tasks(self):
        names = _tool_names(reviewer_mcp)
        assert "tasks" in names

    def test_cannot_create_or_update_tasks(self):
        names = _tool_names(reviewer_mcp)
        assert "create_task" not in names
        assert "update_task" not in names

    def test_has_finding_crud_except_decline(self):
        names = _tool_names(reviewer_mcp)
        assert "add_review_finding" in names
        assert "list_review_findings" in names
        assert "reply_to_finding" in names
        assert "resolve_finding" in names

    def test_cannot_decline_findings(self):
        names = _tool_names(reviewer_mcp)
        assert "decline_finding" not in names

    def test_read_only_attachments(self):
        names = _tool_names(reviewer_mcp)
        assert "list_attachments" in names
        assert "read_attachment" in names
        assert "add_attachment" not in names
        assert "delete_attachment" not in names


class TestPlannerToolSet:
    """Planner role should have exactly the expected tools."""

    def test_has_task_crud(self):
        names = _tool_names(planner_mcp)
        assert "tasks" in names
        assert "create_task" in names
        assert "update_task" in names

    def test_read_only_findings(self):
        names = _tool_names(planner_mcp)
        assert "list_review_findings" in names
        assert "add_review_finding" not in names
        assert "resolve_finding" not in names
        assert "decline_finding" not in names
        assert "reply_to_finding" not in names

    def test_no_delete_attachment(self):
        names = _tool_names(planner_mcp)
        assert "list_attachments" in names
        assert "read_attachment" in names
        assert "add_attachment" in names
        assert "delete_attachment" not in names


# ---------------------------------------------------------------------------
# update_task_impl field whitelist tests (#1190)
# ---------------------------------------------------------------------------


class TestUpdateTaskImplWhitelist:
    """update_task_impl should filter fields by allowed_fields frozenset."""

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_swe_cannot_update_title(self, mock_update):
        """SWE passing title= should have it dropped."""
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Old Title", status="todo")
        result = update_task_impl(
            _SWE_UPDATE_FIELDS,
            project="test",
            number=1,
            title="New Title",
            status="work",
        )
        # status should be passed, title should be dropped
        mock_update.assert_called_once_with("test", 1, status="work")
        assert result["title"] == "Old Title"

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_swe_cannot_update_description(self, mock_update):
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Task")
        update_task_impl(
            _SWE_UPDATE_FIELDS,
            project="test",
            number=1,
            description="new desc",
        )
        # description should be dropped, only project/number passed
        mock_update.assert_called_once_with("test", 1)

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_swe_cannot_update_plan(self, mock_update):
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Task")
        update_task_impl(
            _SWE_UPDATE_FIELDS,
            project="test",
            number=1,
            plan="new plan",
        )
        mock_update.assert_called_once_with("test", 1)

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_planner_cannot_update_report(self, mock_update):
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Task")
        update_task_impl(
            _PLANNER_UPDATE_FIELDS,
            project="test",
            number=1,
            report="done",
        )
        mock_update.assert_called_once_with("test", 1)

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_dropped_fields_are_logged(self, mock_update, caplog):
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Task")
        with caplog.at_level(logging.WARNING, logger="ralph-tasks.mcp"):
            update_task_impl(
                _SWE_UPDATE_FIELDS,
                project="test",
                number=1,
                title="New Title",
            )
        assert "dropped" in caplog.text
        assert "title" in caplog.text

    @patch("ralph_tasks.mcp.tools._update_task")
    def test_none_values_are_silently_skipped(self, mock_update, caplog):
        from ralph_tasks.core import Task

        mock_update.return_value = Task(number=1, title="Task")
        with caplog.at_level(logging.WARNING, logger="ralph-tasks.mcp"):
            update_task_impl(
                _SWE_UPDATE_FIELDS,
                project="test",
                number=1,
                status=None,
                report=None,
            )
        # None values are not "dropped" — they're just unused
        assert "dropped" not in caplog.text
        mock_update.assert_called_once_with("test", 1)


# ---------------------------------------------------------------------------
# _get_review_type tests (#1193)
# ---------------------------------------------------------------------------


class TestGetReviewType:
    """Tests for review_type extraction from MCP context."""

    def test_extracts_review_type_from_context(self):
        """Normal case: review_type in query params."""
        ctx = MagicMock()
        ctx.request_context.request.query_params = {"review_type": "security"}
        assert _get_review_type(ctx) == "security"

    def test_strips_whitespace(self):
        ctx = MagicMock()
        ctx.request_context.request.query_params = {"review_type": "  code-review  "}
        assert _get_review_type(ctx) == "code-review"

    def test_raises_for_empty_review_type(self):
        ctx = MagicMock()
        ctx.request_context.request.query_params = {"review_type": ""}
        with pytest.raises(ValueError, match="review_type query parameter is required"):
            _get_review_type(ctx)

    def test_raises_for_whitespace_only_review_type(self):
        ctx = MagicMock()
        ctx.request_context.request.query_params = {"review_type": "   "}
        with pytest.raises(ValueError, match="review_type query parameter is required"):
            _get_review_type(ctx)

    def test_raises_for_missing_review_type(self):
        ctx = MagicMock()
        ctx.request_context.request.query_params = {}
        # .get("review_type", "") returns ""
        with pytest.raises(ValueError, match="review_type query parameter is required"):
            _get_review_type(ctx)

    def test_attribute_error_raises_value_error(self):
        """When context API is broken, should raise ValueError (not AttributeError)."""
        ctx = MagicMock(spec=[])  # Empty spec — no attributes
        with pytest.raises(ValueError, match="review_type query parameter is required"):
            _get_review_type(ctx)

    def test_request_context_none_raises_value_error(self):
        """When MCP session not yet established, request_context is None."""
        ctx = MagicMock()
        ctx.request_context = None
        with pytest.raises(ValueError, match="review_type query parameter is required"):
            _get_review_type(ctx)


# ---------------------------------------------------------------------------
# _validate_source_path tests (#1205 — path traversal prevention)
# ---------------------------------------------------------------------------


class TestValidateSourcePath:
    """source_path must be under /workspace or /tmp."""

    def test_workspace_path_allowed(self):
        result = _validate_source_path("/workspace/some/file.txt")
        assert str(result).startswith("/workspace")

    def test_tmp_path_allowed(self):
        result = _validate_source_path("/tmp/ralph-attachments/file.txt")
        assert str(result).startswith("/tmp")

    def test_etc_passwd_rejected(self):
        with pytest.raises(ValueError, match="source_path must be under"):
            _validate_source_path("/etc/passwd")

    def test_home_ssh_rejected(self):
        with pytest.raises(ValueError, match="source_path must be under"):
            _validate_source_path("/home/claude/.ssh/id_rsa")

    def test_traversal_via_dotdot_rejected(self):
        with pytest.raises(ValueError, match="source_path must be under"):
            _validate_source_path("/workspace/../etc/passwd")

    def test_resolved_path_returned(self):
        """Returned path should be resolved (no .. components)."""
        result = _validate_source_path("/workspace/a/../b/file.txt")
        assert ".." not in str(result)
