"""MCP role endpoint for Reviewer.

Mounted at ``/mcp-review?review_type=<type>``.
Read-only task access.  Can add/resolve findings and reply to them.
Cannot decline findings, create/update tasks, or add/delete attachments
(read-only attachment access via list and read).

``review_type`` is extracted from the URL query parameter and injected
into tool calls automatically — the reviewer never specifies it explicitly.
"""

from __future__ import annotations

import logging

from fastmcp import Context, FastMCP
from starlette.requests import HTTPConnection

from .tools import (
    add_review_finding_impl,
    list_attachments_impl,
    list_review_findings_impl,
    read_attachment_impl,
    reply_to_finding_impl,
    resolve_finding_impl,
    tasks_impl,
)

logger = logging.getLogger("ralph-tasks.mcp.reviewer")

mcp = FastMCP("ralph-tasks-reviewer")


def _get_review_type(ctx: Context) -> str:
    """Extract review_type from the MCP request context.

    FastMCP exposes the underlying HTTP request via ``ctx.request_context.request``
    (a Starlette ``HTTPConnection``).
    """
    try:
        req_ctx = ctx.request_context
        if req_ctx is None:
            raise AttributeError("request_context is None")
        request: HTTPConnection = req_ctx.request
        review_type = request.query_params.get("review_type", "")
    except AttributeError:
        logger.warning(
            "Failed to extract review_type from MCP context — context API may have changed"
        )
        review_type = ""
    if not review_type.strip():
        raise ValueError("review_type query parameter is required for /mcp-review")
    return review_type.strip()


# ---------------------------------------------------------------------------
# Tasks (read-only)
# ---------------------------------------------------------------------------


@mcp.tool
def tasks(project: str | None = None, number: int | None = None) -> dict | list:
    """Universal task query tool (read-only).

    Args:
        project: Optional project name to filter by
        number: Optional task number (requires project)
    """
    return tasks_impl(project, number)


# ---------------------------------------------------------------------------
# Review Findings
# ---------------------------------------------------------------------------


@mcp.tool
def add_review_finding(
    ctx: Context,
    project: str,
    number: int,
    text: str,
    author: str,
    file: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict:
    """Add a review finding to a task.

    review_type is taken from the session context (URL query parameter).

    Args:
        project: Project name
        number: Task number
        text: Finding description
        author: Who found it (agent/skill name)
        file: Optional file path
        line_start: Optional start line number
        line_end: Optional end line number
    """
    review_type = _get_review_type(ctx)
    return add_review_finding_impl(
        project,
        number,
        review_type,
        text,
        author,
        file=file,
        line_start=line_start,
        line_end=line_end,
    )


@mcp.tool
def list_review_findings(
    ctx: Context,
    project: str,
    number: int,
    status: str | None = None,
) -> list[dict]:
    """List review findings (filtered by session's review_type).

    Args:
        project: Project name
        number: Task number
        status: Optional filter by status (open/resolved/declined)
    """
    review_type = _get_review_type(ctx)
    return list_review_findings_impl(project, number, review_type=review_type, status=status)


@mcp.tool
def reply_to_finding(finding_id: str, text: str, author: str) -> dict:
    """Add a comment to a finding.

    Args:
        finding_id: Finding element_id
        text: Comment text
        author: Comment author
    """
    return reply_to_finding_impl(finding_id, text, author)


@mcp.tool
def resolve_finding(finding_id: str, response: str | None = None) -> dict:
    """Mark a finding as resolved.

    Args:
        finding_id: Finding element_id
        response: Optional description of what was done
    """
    return resolve_finding_impl(finding_id, response=response)


# ---------------------------------------------------------------------------
# Attachments (read-only)
# ---------------------------------------------------------------------------


@mcp.tool
def list_attachments(project: str, number: int) -> list[dict]:
    """List attachments for a task (read-only).

    Args:
        project: Project name
        number: Task number
    """
    return list_attachments_impl(project, number)


@mcp.tool
def read_attachment(project: str, number: int, filename: str) -> dict:
    """Download an attachment to a local temp path for reading (read-only).

    Args:
        project: Project name
        number: Task number
        filename: Name of the attachment file
    """
    return read_attachment_impl(project, number, filename)
