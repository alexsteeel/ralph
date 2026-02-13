"""Simple web UI for task cloud visualization."""

import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .core import (
    BASE_DIR,
    VALID_STATUSES,
    Task,
    add_attachment,
    delete_attachment,
    delete_task,
    get_attachment_path,
    get_backup_path,
    get_config,
    get_next_task_number,
    get_project_description,
    get_project_dir,
    list_attachments,
    list_projects,
    list_tasks,
    read_task,
    set_backup_path,
    set_config,
    set_project_description,
    write_task,
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
        f"Templates directory not found. Searched:\n"
        f"  - {local}\n"
        f"  - {installed}\n"
        f"  - {user_data}"
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


def get_task_month(task) -> str | None:
    """Get month string for task based on status."""
    from datetime import datetime

    if task.status in ("done", "approved"):
        if task.completed:
            return task.completed[:7]  # "YYYY-MM"
    elif task.status == "work":
        if task.started:
            return task.started[:7]
    elif task.status == "todo":
        # Use mtime for todo tasks
        if task.mtime:
            dt = datetime.fromtimestamp(task.mtime)
            return dt.strftime("%Y-%m")
    return None


@app.get("/", response_class=HTMLResponse)
async def projects_cloud(request: Request):
    """Display projects as a cloud."""
    from collections import defaultdict

    projects = []
    # Summary stats across all projects
    summary = {"total": 0, "hold": 0, "work": 0, "todo": 0, "done": 0, "approved": 0}
    # Monthly stats: {month: {todo: N, work: N, done: N, approved: N}}
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
        # Accumulate summary
        for key in summary:
            summary[key] += stats[key]
        # Accumulate monthly stats by status
        for t in tasks:
            month = get_task_month(t)
            if month and t.status in ("todo", "work", "done", "approved"):
                monthly_stats[month][t.status] += 1

    # Sort by month descending, take last 6 months
    monthly_list = sorted(monthly_stats.items(), reverse=True)[:6]

    return templates.TemplateResponse("projects.html", {
        "request": request,
        "projects": projects,
        "summary": summary,
        "project_count": len(projects),
        "monthly": monthly_list,
    })


@app.get("/api/monthly/{month}")
async def get_monthly_tasks(month: str):
    """Get tasks for a specific month (format: YYYY-MM)."""
    from datetime import datetime

    tasks_list = []
    for project_name in list_projects():
        for t in list_tasks(project_name):
            task_month = get_task_month(t)
            if task_month == month and t.status in ("todo", "work", "done", "approved"):
                # Determine the date to use for sorting
                if t.status in ("done", "approved"):
                    date_str = t.completed or ""
                elif t.status == "work":
                    date_str = t.started or ""
                else:  # todo
                    date_str = datetime.fromtimestamp(t.mtime).strftime("%Y-%m-%d %H:%M") if t.mtime else ""

                tasks_list.append({
                    "project": project_name,
                    "number": t.number,
                    "description": t.description,
                    "status": t.status,
                    "date": date_str,
                })

    # Sort by date descending (newest first)
    tasks_list.sort(key=lambda x: x["date"], reverse=True)
    return {"month": month, "tasks": tasks_list}


@app.get("/project/{name}", response_class=HTMLResponse)
async def tasks_cloud(request: Request, name: str):
    """Display tasks of a project as a cloud."""
    tasks = list_tasks(name)
    return templates.TemplateResponse("tasks.html", {
        "request": request,
        "project": name,
        "tasks": tasks,
    })


@app.get("/kanban/{name}", response_class=HTMLResponse)
async def kanban_board(request: Request, name: str):
    """Display tasks as a kanban board."""
    tasks = list_tasks(name)
    # Sort all columns by file modification time (most recent first)
    board = {
        "hold": sorted([t for t in tasks if t.status == "hold"], key=lambda t: t.mtime, reverse=True),
        "todo": sorted([t for t in tasks if t.status == "todo"], key=lambda t: t.mtime, reverse=True),
        "work": sorted([t for t in tasks if t.status == "work"], key=lambda t: t.mtime, reverse=True),
        "done": sorted([t for t in tasks if t.status == "done"], key=lambda t: t.mtime, reverse=True),
        "approved": sorted([t for t in tasks if t.status == "approved"], key=lambda t: t.mtime, reverse=True),
    }
    return templates.TemplateResponse("kanban.html", {
        "request": request,
        "project": name,
        "board": board,
    })


@app.get("/api/task/{project}/{number}")
async def get_task_endpoint(project: str, number: int):
    """Get task data."""
    task = read_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.post("/api/task/{project}/{number}")
async def update_task_endpoint(project: str, number: int, data: TaskUpdate):
    """Update task body, plan, or description."""
    task = read_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if data.body is not None:
        task.body = data.body
    if data.plan is not None:
        task.plan = data.plan
    if data.report is not None:
        task.report = data.report
    if data.review is not None:
        task.review = data.review
    if data.blocks is not None:
        task.blocks = data.blocks
    if data.description is not None:
        task.description = data.description
    if data.status is not None and data.status in VALID_STATUSES:
        old_status = task.status
        task.status = data.status
        # Auto-set started when moving to work
        if data.status == "work" and old_status != "work" and not task.started:
            task.started = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Auto-set completed when moving to done/approved
        if data.status in ("done", "approved") and old_status not in ("done", "approved") and not task.completed:
            task.completed = datetime.now().strftime("%Y-%m-%d %H:%M")

    write_task(project, task)
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
    # Create project directory
    get_project_dir(name, create=True)
    if data.description:
        set_project_description(name, data.description)
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

    # Ensure project exists
    get_project_dir(project, create=True)

    task_number = get_next_task_number(project)
    task = Task(
        number=task_number,
        description=data.description.strip(),
        body=data.body or "",
        plan=data.plan or "",
    )

    write_task(project, task)
    return {"ok": True, "number": task_number, "task": task.to_dict()}


# =============================================================================
# Attachments API
# =============================================================================


@app.get("/api/task/{project}/{number}/attachments")
async def list_attachments_endpoint(project: str, number: int):
    """List all attachments for a task."""
    task = read_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"ok": True, "attachments": list_attachments(project, number)}


@app.post("/api/task/{project}/{number}/attachments")
async def upload_attachment_endpoint(project: str, number: int, file: UploadFile = File(...)):  # noqa: B008
    """Upload an attachment to a task."""
    task = read_task(project, number)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    file_path = add_attachment(project, number, file.filename, content)

    return {
        "ok": True,
        "name": file_path.name,
        "path": str(file_path),
        "size": len(content),
    }


@app.get("/api/task/{project}/{number}/attachments/{filename:path}")
async def download_attachment_endpoint(project: str, number: int, filename: str):
    """Download an attachment."""
    file_path = get_attachment_path(project, number, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@app.delete("/api/task/{project}/{number}/attachments/{filename:path}")
async def delete_attachment_endpoint(project: str, number: int, filename: str):
    """Delete an attachment."""
    if delete_attachment(project, number, filename):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Attachment not found")


# =============================================================================
# Settings API
# =============================================================================

class SettingsUpdate(BaseModel):
    backup_path: str | None = None


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    return {
        "backup_path": str(get_backup_path()) if get_backup_path() else None,
        "last_backup": get_config().get("last_backup"),
    }


@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    """Update settings."""
    if settings.backup_path is not None:
        # Validate path
        if settings.backup_path:
            path = Path(settings.backup_path).expanduser()
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Cannot create backup path: {e}") from e
        set_backup_path(settings.backup_path if settings.backup_path else None)
    return {"ok": True}


# =============================================================================
# Backup functionality
# =============================================================================

def do_backup() -> bool:
    """Perform backup if there are changes since last backup."""
    import hashlib
    import shutil

    backup_path = get_backup_path()
    if not backup_path:
        return False

    # Calculate hash of all task files to detect changes
    def calc_hash() -> str:
        h = hashlib.md5()
        for project in sorted(list_projects()):
            for task in sorted(list_tasks(project), key=lambda t: t.number):
                h.update(f"{project}/{task.number}/{task.mtime}".encode())
        return h.hexdigest()

    current_hash = calc_hash()
    config = get_config()
    last_hash = config.get("last_backup_hash")

    if current_hash == last_hash:
        return False  # No changes

    # Create backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H")
    backup_dir = backup_path / timestamp

    if backup_dir.exists():
        return False  # Already backed up this hour

    try:
        shutil.copytree(BASE_DIR, backup_dir, ignore=shutil.ignore_patterns("config.json"))
        config["last_backup"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        config["last_backup_hash"] = current_hash
        set_config(config)
        return True
    except Exception as e:
        print(f"Backup failed: {e}")
        return False


async def backup_scheduler():
    """Background task to run backup every hour."""
    import asyncio
    while True:
        await asyncio.sleep(3600)  # Wait 1 hour
        try:
            if do_backup():
                print(f"Backup completed at {datetime.now()}")
        except Exception as e:
            print(f"Backup error: {e}")


@app.on_event("startup")
async def start_backup_scheduler():
    """Start the backup scheduler on app startup."""
    import asyncio
    asyncio.create_task(backup_scheduler())


@app.post("/api/backup")
async def trigger_backup():
    """Manually trigger a backup."""
    if not get_backup_path():
        raise HTTPException(status_code=400, detail="Backup path not configured")
    if do_backup():
        return {"ok": True, "message": "Backup created"}
    return {"ok": True, "message": "No changes to backup"}


def main():
    """Run the web server."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
