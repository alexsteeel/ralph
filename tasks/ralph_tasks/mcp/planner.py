"""MCP role endpoint for Planner.

Mounted at ``/mcp-plan``.
Can create/update tasks (including title, description, plan, blocks).
Cannot update report section.  Read-only access to review findings.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .tools import (
    add_attachment_impl,
    create_task_impl,
    list_attachments_impl,
    list_review_findings_impl,
    read_attachment_impl,
    tasks_impl,
    update_task_impl,
)

mcp = FastMCP("ralph-tasks-planner")

# Allowed fields for Planner update_task (no report)
_PLANNER_UPDATE_FIELDS = frozenset(
    {
        "title",
        "description",
        "plan",
        "blocks",
        "status",
        "module",
        "depends_on",
        "branch",
        "started",
        "completed",
    }
)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@mcp.tool
def tasks(project: str | None = None, number: int | None = None) -> dict | list:
    """Universal task query tool.

    Args:
        project: Optional project name to filter by
        number: Optional task number (requires project)
    """
    return tasks_impl(project, number)


@mcp.tool
def create_task(
    project: str,
    title: str,
    description: str = "",
    plan: str = "",
) -> dict:
    """Create a new task in a project.

    Args:
        project: Project name (created if doesn't exist)
        title: Short task title
        description: Optional detailed description
        plan: Optional implementation plan
    """
    return create_task_impl(project, title, description=description, plan=plan)


@mcp.tool
def update_task(
    project: str,
    number: int,
    *,
    title: str | None = None,
    description: str | None = None,
    plan: str | None = None,
    blocks: str | None = None,
    status: str | None = None,
    module: str | None = None,
    depends_on: list[int] | None = None,
    branch: str | None = None,
    started: str | None = None,
    completed: str | None = None,
) -> dict:
    """Update task fields (Planner role — cannot modify report).

    Args:
        project: Project name
        number: Task number to update
        title: New short title
        description: New detailed description
        plan: New implementation plan content
        blocks: Blocking issues description
        status: New status (todo, work, done, hold, approved)
        module: Module/area name
        depends_on: List of task numbers this task depends on
        branch: Git branch name
        started: Started datetime (YYYY-MM-DD HH:MM)
        completed: Completed datetime (YYYY-MM-DD HH:MM)
    """
    return update_task_impl(
        _PLANNER_UPDATE_FIELDS,
        project=project,
        number=number,
        title=title,
        description=description,
        plan=plan,
        blocks=blocks,
        status=status,
        module=module,
        depends_on=depends_on,
        branch=branch,
        started=started,
        completed=completed,
    )


# ---------------------------------------------------------------------------
# Review Findings (read-only)
# ---------------------------------------------------------------------------


@mcp.tool
def list_review_findings(
    project: str,
    number: int,
    review_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List review findings with comment threads (read-only).

    Args:
        project: Project name
        number: Task number
        review_type: Optional filter by review type
        status: Optional filter by status (open/resolved/declined)
    """
    return list_review_findings_impl(project, number, review_type=review_type, status=status)


# ---------------------------------------------------------------------------
# Attachments (read + add, no delete)
# ---------------------------------------------------------------------------


@mcp.tool
def list_attachments(project: str, number: int) -> list[dict]:
    """List attachments for a task.

    Args:
        project: Project name
        number: Task number
    """
    return list_attachments_impl(project, number)


@mcp.tool
def read_attachment(project: str, number: int, filename: str) -> dict:
    """Download an attachment to a local temp path for reading.

    Args:
        project: Project name
        number: Task number
        filename: Name of the attachment file
    """
    return read_attachment_impl(project, number, filename)


@mcp.tool
def add_attachment(
    project: str,
    number: int,
    source_path: str,
    filename: str | None = None,
) -> dict:
    """Copy a file to task attachments.

    Args:
        project: Project name
        number: Task number
        source_path: Path to source file to copy
        filename: Optional new filename (default: use source filename)
    """
    return add_attachment_impl(project, number, source_path, filename)
