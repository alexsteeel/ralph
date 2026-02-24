"""Shared tool implementations for MCP role endpoints.

All functions are plain helpers that call into ``core.*``.
Role-specific FastMCP files (swe.py, reviewer.py, planner.py) register
decorated wrappers that delegate to these implementations.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from .. import storage
from ..core import (
    VALID_STATUSES,
    copy_attachment,
    get_attachment_bytes,
    normalize_project_name,
    project_exists,
)
from ..core import add_review_finding as _add_review_finding
from ..core import create_task as _create_task
from ..core import decline_finding as _decline_finding
from ..core import delete_attachment as _delete_attachment
from ..core import get_task as _get_task
from ..core import list_attachments as _list_attachments
from ..core import list_projects as _list_projects
from ..core import list_review_findings as _list_review_findings
from ..core import list_tasks as _list_tasks
from ..core import reply_to_finding as _reply_to_finding
from ..core import resolve_finding as _resolve_finding
from ..core import search_tasks as _search_tasks
from ..core import update_task as _update_task

logger = logging.getLogger("ralph-tasks.mcp")

# Temp directory for read_attachment downloads
_ATTACHMENT_CACHE_DIR = Path(tempfile.gettempdir()) / "ralph-attachments"


def _require_task(project: str, number: int) -> None:
    """Validate that a project and task exist, raising ValueError if not."""
    if not project_exists(project):
        raise ValueError(f"Project '{project}' does not exist")
    if _get_task(project, number) is None:
        raise ValueError(f"Task #{number} not found in project '{project}'")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def tasks_impl(project: str | None = None, number: int | None = None) -> dict | list:
    """Universal task query."""
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
                        {"number": t.number, "title": t.title, "status": t.status}
                        for t in proj_tasks
                    ],
                }
            )
        return result

    if not project_exists(project):
        raise ValueError(f"Project '{project}' does not exist")

    if number is None:
        proj_tasks = _list_tasks(project)
        return [{"number": t.number, "title": t.title, "status": t.status} for t in proj_tasks]

    task = _get_task(project, number)
    if task is None:
        raise ValueError(f"Task #{number} not found in project '{project}'")
    return task.to_dict()


def search_tasks_impl(
    project: str,
    query: str,
    status: str | None = None,
    module: str | None = None,
) -> list[dict]:
    """Search tasks by keywords across all text fields."""
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    if len(query.strip().split()) > 20:
        raise ValueError("query must not exceed 20 keywords")
    if status and status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Valid statuses: {', '.join(sorted(VALID_STATUSES))}"
        )
    if not project_exists(project):
        raise ValueError(f"Project '{project}' does not exist")
    results = _search_tasks(project, query, status=status, module=module)
    return [r.to_dict() for r in results]


def create_task_impl(
    project: str,
    title: str,
    description: str = "",
    plan: str = "",
) -> dict:
    """Create a new task."""
    task = _create_task(project, title, description=description, plan=plan)
    return task.to_dict()


def update_task_impl(allowed_fields: frozenset[str], **kwargs: Any) -> dict:
    """Update task fields, filtering to only allowed fields.

    ``project`` and ``number`` are always required.
    Fields with ``None`` values are silently skipped (use ``""`` to clear).
    Non-allowed fields with non-None values are logged as warnings.
    """
    project = kwargs.pop("project")
    number = kwargs.pop("number")
    dropped = {k for k, v in kwargs.items() if v is not None and k not in allowed_fields}
    if dropped:
        logger.warning(
            "update_task: fields %s dropped (not in allowed set) for %s#%s",
            dropped,
            project,
            number,
        )
    fields = {k: v for k, v in kwargs.items() if v is not None and k in allowed_fields}
    task = _update_task(project, number, **fields)
    return task.to_dict()


# ---------------------------------------------------------------------------
# Review Findings
# ---------------------------------------------------------------------------


def add_review_finding_impl(
    project: str,
    number: int,
    review_type: str,
    text: str,
    author: str,
    file: str | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict:
    return _add_review_finding(
        project,
        number,
        review_type,
        text,
        author,
        file=file,
        line_start=line_start,
        line_end=line_end,
    )


def list_review_findings_impl(
    project: str,
    number: int,
    review_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    return _list_review_findings(project, number, review_type=review_type, status=status)


def reply_to_finding_impl(finding_id: str, text: str, author: str) -> dict:
    return _reply_to_finding(finding_id, text, author)


def resolve_finding_impl(finding_id: str, response: str | None = None) -> dict:
    return _resolve_finding(finding_id, response=response)


def decline_finding_impl(finding_id: str, reason: str) -> dict:
    return _decline_finding(finding_id, reason)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


def list_attachments_impl(project: str, number: int) -> list[dict]:
    _require_task(project, number)
    return _list_attachments(project, number)


_ALLOWED_ATTACHMENT_ROOTS = (Path("/workspace"), Path(tempfile.gettempdir()))


def _validate_source_path(source_path: str) -> Path:
    """Resolve source_path and ensure it's under an allowed root directory."""
    resolved = Path(source_path).resolve()
    for root in _ALLOWED_ATTACHMENT_ROOTS:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(r) for r in _ALLOWED_ATTACHMENT_ROOTS)
    raise ValueError(f"source_path must be under one of: {allowed}; got {source_path}")


def add_attachment_impl(
    project: str,
    number: int,
    source_path: str,
    filename: str | None = None,
) -> dict:
    _require_task(project, number)
    validated_path = _validate_source_path(source_path)
    result = copy_attachment(project, number, str(validated_path), filename)
    return {"ok": True, **result}


def read_attachment_impl(project: str, number: int, filename: str) -> dict:
    _require_task(project, number)
    content = get_attachment_bytes(project, number, filename)
    if content is None:
        raise ValueError(f"Attachment '{filename}' not found for task #{number}")

    safe_project = "".join(c for c in normalize_project_name(project) if c.isalnum() or c in "-_")
    safe_name = storage.sanitize_filename(filename)
    cache_dir = _ATTACHMENT_CACHE_DIR / safe_project / f"{number:03d}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / safe_name
    local_path.write_bytes(content)

    return {
        "ok": True,
        "name": safe_name,
        "path": str(local_path),
        "size": len(content),
    }


def delete_attachment_impl(project: str, number: int, filename: str) -> dict:
    _require_task(project, number)
    if not _delete_attachment(project, number, filename):
        raise ValueError(f"Attachment '{filename}' not found for task #{number}")
    return {"ok": True}
