"""MCP role endpoint for SWE (developer).

Mounted at ``/mcp-swe``.  Full task access except title/description/plan
sections (those belong to the Planner role).
"""

from __future__ import annotations

from fastmcp import FastMCP

from .tools import (
    add_attachment_impl,
    create_task_impl,
    decline_finding_impl,
    delete_attachment_impl,
    list_attachments_impl,
    list_review_findings_impl,
    read_attachment_impl,
    reply_to_finding_impl,
    search_tasks_impl,
    tasks_impl,
    update_task_impl,
)

mcp = FastMCP("ralph-tasks-swe")

# Allowed fields for SWE update_task (no title, description, plan)
_SWE_UPDATE_FIELDS = frozenset(
    {
        "status",
        "module",
        "branch",
        "started",
        "completed",
        "depends_on",
        "report",
        "blocks",
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

    Returns:
        - tasks() -> list of projects with task summaries
        - tasks(project) -> list of tasks in project
        - tasks(project, number) -> full task details including plan
    """
    return tasks_impl(project, number)


@mcp.tool
def search_tasks(
    project: str,
    query: str,
    status: str | None = None,
    module: str | None = None,
) -> list[dict]:
    """Search tasks by keywords across all text fields.

    Args:
        project: Project name
        query: Space-separated keywords (all must match, AND logic)
        status: Optional filter by status (todo, work, done, hold, approved)
        module: Optional filter by module

    Returns:
        List of matching tasks with number, title, status, and snippet
    """
    return search_tasks_impl(project, query, status=status, module=module)


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

    Returns:
        Created task details including number
    """
    return create_task_impl(project, title, description=description, plan=plan)


@mcp.tool
def update_task(
    project: str,
    number: int,
    *,
    status: str | None = None,
    module: str | None = None,
    branch: str | None = None,
    started: str | None = None,
    completed: str | None = None,
    depends_on: list[int] | None = None,
    report: str | None = None,
    blocks: str | None = None,
) -> dict:
    """Update task fields (SWE role — cannot modify title, description, plan).

    Args:
        project: Project name
        number: Task number to update
        status: New status (todo, work, done, hold, approved)
        module: Module/area name
        branch: Git branch name
        started: Started datetime (YYYY-MM-DD HH:MM)
        completed: Completed datetime (YYYY-MM-DD HH:MM)
        depends_on: List of task numbers this task depends on
        report: Task completion report
        blocks: Blocking issues description

    Returns:
        Updated task details
    """
    return update_task_impl(
        _SWE_UPDATE_FIELDS,
        project=project,
        number=number,
        status=status,
        module=module,
        branch=branch,
        started=started,
        completed=completed,
        depends_on=depends_on,
        report=report,
        blocks=blocks,
    )


# ---------------------------------------------------------------------------
# Review Findings (read + reply + decline)
# ---------------------------------------------------------------------------


@mcp.tool
def list_review_findings(
    project: str,
    number: int,
    review_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List review findings with comment threads.

    Args:
        project: Project name
        number: Task number
        review_type: Optional filter by review type
        status: Optional filter by status (open/resolved/declined)
    """
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
def decline_finding(finding_id: str, reason: str) -> dict:
    """Mark a finding as declined.

    Args:
        finding_id: Finding element_id
        reason: Mandatory reason for declining
    """
    return decline_finding_impl(finding_id, reason)


# ---------------------------------------------------------------------------
# Attachments (full access)
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
def delete_attachment(project: str, number: int, filename: str) -> dict:
    """Delete an attachment from a task.

    Args:
        project: Project name
        number: Task number
        filename: Name of the attachment file to delete
    """
    return delete_attachment_impl(project, number, filename)
