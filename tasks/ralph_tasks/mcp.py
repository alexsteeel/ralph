"""
Ralph Tasks MCP: Markdown-based task management MCP server for Claude Code.

Optimized 3-tool design:
- tasks()              - Universal read (list projects, tasks, or get task details)
- create_task()        - Create new task
- update_task()        - Update any task field
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastmcp import FastMCP
from starlette.applications import Starlette

from .core import (
    copy_attachment,
    get_attachment_bytes,
    project_exists,
)
from .core import (
    create_task as _create_task,
)
from .core import (
    delete_attachment as _delete_attachment,
)
from .core import (
    get_task as _get_task,
)
from .core import (
    list_attachments as _list_attachments,
)
from .core import (
    list_projects as _list_projects,
)
from .core import (
    list_tasks as _list_tasks,
)
from .core import (
    update_task as _update_task,
)

mcp = FastMCP("ralph-tasks")

# Temp directory for read_attachment downloads
_ATTACHMENT_CACHE_DIR = Path(tempfile.gettempdir()) / "ralph-attachments"


def _require_task(project: str, number: int) -> None:
    """Validate that a project and task exist, raising ValueError if not."""
    if not project_exists(project):
        raise ValueError(f"Project '{project}' does not exist")
    if _get_task(project, number) is None:
        raise ValueError(f"Task #{number} not found in project '{project}'")


@mcp.tool
def tasks(project: str | None = None, number: int | None = None) -> dict | list:
    """
    Universal task query tool.

    Args:
        project: Optional project name to filter by
        number: Optional task number (requires project)

    Returns:
        - tasks() → list of projects with task summaries
        - tasks(project) → list of tasks in project
        - tasks(project, number) → full task details including plan

    Examples:
        tasks()                    # List all projects with task counts
        tasks("my-project")        # List tasks in my-project
        tasks("my-project", 1)     # Get full details of task #1
    """
    # No args: list all projects with task summaries
    if project is None:
        projects = _list_projects()
        result = []
        for proj in projects:
            proj_tasks = _list_tasks(proj)
            result.append(
                {
                    "project": proj,
                    "task_count": len(proj_tasks),
                    "by_status": {
                        "work": sum(1 for t in proj_tasks if t.status == "work"),
                        "todo": sum(1 for t in proj_tasks if t.status == "todo"),
                        "done": sum(1 for t in proj_tasks if t.status == "done"),
                    },
                    "tasks": [
                        {"number": t.number, "description": t.description, "status": t.status}
                        for t in proj_tasks
                    ],
                }
            )
        return result

    # Project specified: check it exists
    if not project_exists(project):
        raise ValueError(f"Project '{project}' does not exist")

    # Project only: list tasks in project
    if number is None:
        proj_tasks = _list_tasks(project)
        return [
            {"number": t.number, "description": t.description, "status": t.status}
            for t in proj_tasks
        ]

    # Project + number: get full task details
    task = _get_task(project, number)
    if task is None:
        raise ValueError(f"Task #{number} not found in project '{project}'")

    return task.to_dict()


@mcp.tool
def create_task(
    project: str,
    description: str,
    body: str = "",
    plan: str = "",
) -> dict:
    """
    Create a new task in a project.

    Args:
        project: Project name (created if doesn't exist)
        description: Short task description (used in filename)
        body: Optional detailed description
        plan: Optional implementation plan

    Returns:
        Created task details including number and file path
    """
    task = _create_task(project, description, body=body, plan=plan)
    return task.to_dict()


@mcp.tool
def update_task(
    project: str,
    number: int,
    description: str | None = None,
    status: str | None = None,
    module: str | None = None,
    plan: str | None = None,
    body: str | None = None,
    report: str | None = None,
    review: str | None = None,
    branch: str | None = None,
    started: str | None = None,
    completed: str | None = None,
    depends_on: list[int] | None = None,
) -> dict:
    """
    Update any task field.

    Args:
        project: Project name
        number: Task number to update
        description: New short description
        status: New status (todo, work, done)
        module: Module/area name (e.g., "auth", "api", "ui")
        plan: New implementation plan content
        body: New detailed description
        report: Task completion report
        review: Code review feedback
        branch: Git branch name
        started: Started datetime (YYYY-MM-DD HH:MM)
        completed: Completed datetime (YYYY-MM-DD HH:MM)
        depends_on: List of task numbers this task depends on

    Returns:
        Updated task details
    """
    fields = {
        key: val
        for key, val in {
            "description": description,
            "status": status,
            "module": module,
            "plan": plan,
            "body": body,
            "report": report,
            "review": review,
            "branch": branch,
            "started": started,
            "completed": completed,
            "depends_on": depends_on,
        }.items()
        if val is not None
    }

    task = _update_task(project, number, **fields)
    return task.to_dict()


# =============================================================================
# Attachment tools
# =============================================================================


@mcp.tool
def list_attachments(project: str, number: int) -> list[dict]:
    """
    List attachments for a task.

    Args:
        project: Project name
        number: Task number

    Returns:
        List of attachments: [{"name": "file.png", "size": 1234}, ...]

    Note:
        Use read_attachment tool to download an attachment for viewing.
        Then use Claude's Read tool on the returned path.
    """
    _require_task(project, number)
    return _list_attachments(project, number)


@mcp.tool
def add_attachment(
    project: str,
    number: int,
    source_path: str,
    filename: str | None = None,
) -> dict:
    """
    Copy a file to task attachments.

    Args:
        project: Project name
        number: Task number
        source_path: Path to source file to copy
        filename: Optional new filename (default: use source filename)

    Returns:
        {"ok": True, "name": "filename", "size": 1234}
    """
    _require_task(project, number)
    result = copy_attachment(project, number, source_path, filename)
    return {"ok": True, **result}


@mcp.tool
def read_attachment(project: str, number: int, filename: str) -> dict:
    """
    Download an attachment from MinIO to a local temp path for reading.

    Args:
        project: Project name
        number: Task number
        filename: Name of the attachment file

    Returns:
        {"ok": True, "name": "filename", "path": "/tmp/ralph-attachments/...", "size": 1234}

    Note:
        Use Claude's Read tool on the returned path to view the file.
        Read tool supports images (PNG, JPG, etc.) natively.
    """
    _require_task(project, number)

    content = get_attachment_bytes(project, number, filename)
    if content is None:
        raise ValueError(f"Attachment '{filename}' not found for task #{number}")

    # Write to temp location (sanitize project name for filesystem path)
    safe_project = "".join(c for c in project if c.isalnum() or c in "-_.")
    safe_name = Path(filename).name
    cache_dir = _ATTACHMENT_CACHE_DIR / safe_project / f"{number:03d}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / safe_name
    local_path.write_bytes(content)

    return {
        "ok": True,
        "name": filename,
        "path": str(local_path),
        "size": len(content),
    }


@mcp.tool
def delete_attachment(project: str, number: int, filename: str) -> dict:
    """
    Delete an attachment from a task.

    Args:
        project: Project name
        number: Task number
        filename: Name of the attachment file to delete

    Returns:
        {"ok": True} if deleted, raises error if not found
    """
    _require_task(project, number)
    if not _delete_attachment(project, number, filename):
        raise ValueError(f"Attachment '{filename}' not found for task #{number}")

    return {"ok": True}


def get_mcp_http_app() -> Starlette:
    """Return an ASGI app for the MCP server using streamable-http transport.

    Intended to be mounted into the FastAPI web app at /mcp.
    Uses path="/" so the endpoint is at the mount point itself.
    """
    return mcp.http_app(path="/", transport="streamable-http")


def main():
    """Run the MCP server (stdio transport for local Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
