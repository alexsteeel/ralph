"""Web UI for task management (kanban board + project overview)."""

import io
import sys
from collections import defaultdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .core import (
    Task,
    delete_attachment,
    delete_task,
    get_attachment_bytes,
    get_project_description,
    get_task,
    list_attachments,
    list_projects,
    list_tasks,
    save_attachment,
    set_project_description,
)
from .core import (
    create_project as _create_project,
)
from .core import (
    create_task as _create_task,
)
from .core import (
    update_task as _update_task,
)


def find_templates_dir() -> Path:
    """Find templates directory in various locations."""
    # 1. Local development path (one level up from ralph_tasks/)
    local = Path(__file__).parent.parent / "templates"
    if local.exists():
        return local

    # 2. Installed data path (sys.prefix/share/ralph-tasks/templates)
    installed = Path(sys.prefix) / "share" / "ralph-tasks" / "templates"
    if installed.exists():
        return installed

    # 3. User install path (~/.local/share/ralph-tasks/templates)
    user_data = Path.home() / ".local" / "share" / "ralph-tasks" / "templates"
    if user_data.exists():
        return user_data

    raise RuntimeError(
        f"Templates directory not found. Searched:\n  - {local}\n  - {installed}\n  - {user_data}"
    )


app = FastAPI(title="Task Cloud")
templates = Jinja2Templates(directory=find_templates_dir())


class TaskUpdate(BaseModel):
    body: str | None = None
    plan: str | None = None
    report: str | None = None
    review: str | None = None
    blocks: str | None = None
    description: str | None = None
    status: str | None = None


class TaskCreate(BaseModel):
    description: str
    body: str | None = ""
    plan: str | None = ""


class ProjectCreate(BaseModel):
    name: str
    description: str | None = ""


class ProjectUpdate(BaseModel):
    description: str | None = None


_STATUS_DATE_FIELD = {
    "done": "completed",
    "approved": "completed",
    "work": "started",
    "todo": "updated_at",
}


def get_task_month(task: Task) -> str | None:
    """Get month string (YYYY-MM) for task based on its status."""
    attr = _STATUS_DATE_FIELD.get(task.status)
    if attr is None:
        return None
    value = getattr(task, attr, None)
    return value[:7] if value else None


@app.get("/", response_class=HTMLResponse)
async def projects_cloud(request: Request):
    """Display projects as a cloud."""
    projects = []
    summary = {"total": 0, "hold": 0, "work": 0, "todo": 0, "done": 0, "approved": 0}
    monthly_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"todo": 0, "work": 0, "done": 0, "approved": 0}
    )

    for name in list_projects():
        tasks = list_tasks(name)
        stats = {
            "name": name,
            "description": get_project_description(name),
            "total": len(tasks),
            "hold": sum(1 for t in tasks if t.status == "hold"),
            "work": sum(1 for t in tasks if t.status == "work"),
            "todo": sum(1 for t in tasks if t.status == "todo"),
            "done": sum(1 for t in tasks if t.status == "done"),
            "approved": sum(1 for t in tasks if t.status == "approved"),
        }
        projects.append(stats)
        for key in summary:
            summary[key] += stats[key]
        for t in tasks:
            month = get_task_month(t)
            if month and t.status in ("todo", "work", "done", "approved"):
                monthly_stats[month][t.status] += 1

    monthly_list = sorted(monthly_stats.items(), reverse=True)[:6]

    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "projects": projects,
            "summary": summary,
            "project_count": len(projects),
            "monthly": monthly_list,
        },
    )


@app.get("/api/monthly/{month}")
async def get_monthly_tasks(month: str):
    """Get tasks for a specific month (format: YYYY-MM)."""
    tasks_list = []
    for project_name in list_projects():
        for t in list_tasks(project_name):
            if get_task_month(t) != month:
                continue
            attr = _STATUS_DATE_FIELD.get(t.status)
            if attr is None:
                continue
            date_value = getattr(t, attr, "") or ""
            tasks_list.append(
                {
                    "project": project_name,
                    "number": t.number,
                    "description": t.description,
                    "status": t.status,
                    "date": date_value[:16],
                }
            )

    tasks_list.sort(key=lambda x: x["date"], reverse=True)
    return {"month": month, "tasks": tasks_list}


@app.get("/kanban/{name}", response_class=HTMLResponse)
async def kanban_board(request: Request, name: str):
    """Display tasks as a kanban board."""
    tasks = list_tasks(name)
    board = {
        status: sorted(
            [t for t in tasks if t.status == status],
            key=lambda t: t.updated_at,
            reverse=True,
        )
        for status in ("hold", "todo", "work", "done", "approved")
    }
    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "project": name,
            "board": board,
        },
    )


@app.get("/api/task/{project}/{number}")
async def get_task_endpoint(project: str, number: int):
    """Get task data."""
    task = get_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.post("/api/task/{project}/{number}")
async def update_task_endpoint(project: str, number: int, data: TaskUpdate):
    """Update task body, plan, or description."""
    fields = data.model_dump(exclude_none=True)
    if not fields:
        task = get_task(project, number)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"ok": True, "task": task.to_dict()}

    try:
        task = _update_task(project, number, **fields)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"ok": True, "task": task.to_dict()}


@app.delete("/api/task/{project}/{number}")
async def delete_task_endpoint(project: str, number: int):
    """Delete a task."""
    if delete_task(project, number):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/project")
async def create_project_endpoint(data: ProjectCreate):
    """Create a new project."""
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    _create_project(name, data.description or "")
    return {"ok": True, "name": name}


@app.post("/api/project/{name}")
async def update_project_endpoint(name: str, data: ProjectUpdate):
    """Update project description."""
    if data.description is not None:
        set_project_description(name, data.description)
    return {"ok": True, "description": get_project_description(name)}


@app.post("/api/task/{project}")
async def create_task_endpoint(project: str, data: TaskCreate):
    """Create a new task."""
    if not data.description.strip():
        raise HTTPException(status_code=400, detail="Task description is required")

    task = _create_task(
        project, data.description.strip(), body=data.body or "", plan=data.plan or ""
    )
    return {"ok": True, "number": task.number, "task": task.to_dict()}


# =============================================================================
# Attachments API
# =============================================================================


def _require_task_or_404(project: str, number: int) -> Task:
    """Get a task or raise HTTP 404."""
    task = get_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/task/{project}/{number}/attachments")
async def list_attachments_endpoint(project: str, number: int):
    """List all attachments for a task."""
    _require_task_or_404(project, number)
    return {"ok": True, "attachments": list_attachments(project, number)}


@app.post("/api/task/{project}/{number}/attachments")
async def upload_attachment_endpoint(project: str, number: int, file: UploadFile = File(...)):  # noqa: B008
    """Upload an attachment to a task."""
    _require_task_or_404(project, number)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    result = save_attachment(project, number, file.filename, content)
    return {"ok": True, **result}


@app.get("/api/task/{project}/{number}/attachments/{filename:path}")
async def download_attachment_endpoint(project: str, number: int, filename: str):
    """Download an attachment from MinIO as a streaming response."""
    content = get_attachment_bytes(project, number, filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="{}"'.format(
                Path(filename).name.replace("\\", "\\\\").replace('"', '\\"')
            )
        },
    )


@app.delete("/api/task/{project}/{number}/attachments/{filename:path}")
async def delete_attachment_endpoint(project: str, number: int, filename: str):
    """Delete an attachment."""
    if delete_attachment(project, number, filename):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Attachment not found")


# =============================================================================
# Settings API (simplified — no backup)
# =============================================================================


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    return {}


def main():
    """Run the web server."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
