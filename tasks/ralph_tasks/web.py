"""Web UI for task management (kanban board + project overview)."""

import hmac
import io
import logging
import os
import sys
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__, storage
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
    normalize_project_name,
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
from .mcp import get_planner_mcp_app, get_reviewer_mcp_app, get_swe_mcp_app

logger = logging.getLogger("ralph-tasks.web")

_BEARER_PREFIX = "bearer "
_PROTECTED_PATH_PREFIXES = ("/api/", "/mcp-swe", "/mcp-review", "/mcp-plan")


def _get_configured_api_key() -> str:
    """Return the configured API key, stripped of whitespace."""
    return os.environ.get("RALPH_TASKS_API_KEY", "").strip()


def _extract_token_from_headers(headers: dict[bytes, bytes]) -> str | None:
    """Extract auth token from ASGI headers dict.

    Supports ``Authorization: Bearer <token>`` (case-insensitive prefix per
    RFC 7235) and ``X-API-Key: <token>`` as fallback.
    """
    raw_auth = headers.get(b"authorization", b"")
    try:
        auth_header = raw_auth.decode("ascii")
    except (UnicodeDecodeError, ValueError):
        return None

    if auth_header.lower().startswith(_BEARER_PREFIX):
        return auth_header[len(_BEARER_PREFIX) :].strip()

    raw_api_key = headers.get(b"x-api-key", b"")
    try:
        api_key_header = raw_api_key.decode("ascii")
    except (UnicodeDecodeError, ValueError):
        return None

    return api_key_header or None


class ApiKeyMiddleware:
    """ASGI middleware that protects /api/* and /mcp-* with an API key.

    When RALPH_TASKS_API_KEY env var is set (non-empty after stripping),
    requires ``Authorization: Bearer <key>`` or ``X-API-Key: <key>``
    header on protected paths.  When the env var is empty or unset, all
    requests pass through (backward-compatible, disabled by default).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        api_key = _get_configured_api_key()
        if not api_key:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not any(path.startswith(p) for p in _PROTECTED_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        token = _extract_token_from_headers(headers)

        if token is None or not hmac.compare_digest(token, api_key):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": 'Bearer realm="ralph-tasks"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class ReviewTypeValidationMiddleware:
    """ASGI middleware that validates review_type query parameter on /mcp-review.

    Returns HTTP 400 if the ``review_type`` query parameter is missing.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not path.startswith("/mcp-review"):
            await self.app(scope, receive, send)
            return

        query_string = scope.get("query_string", b"").decode("ascii", errors="replace")
        review_type = parse_qs(query_string).get("review_type", [""])[0].strip()
        if not review_type:
            response = JSONResponse(
                status_code=400,
                content={"detail": "review_type query parameter is required for /mcp-review"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _get_max_upload_bytes() -> int:
    """Return the maximum upload size in bytes from env (default 50 MB)."""
    raw = os.environ.get("RALPH_TASKS_MAX_UPLOAD_MB", "50")
    try:
        mb = int(raw)
    except ValueError:
        logger.warning("Invalid RALPH_TASKS_MAX_UPLOAD_MB=%r, using default 50", raw)
        mb = 50
    if mb <= 0:
        logger.warning("RALPH_TASKS_MAX_UPLOAD_MB=%d is non-positive, using default 50", mb)
        mb = 50
    return mb * 1024 * 1024


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


_swe_mcp_app = get_swe_mcp_app()
_reviewer_mcp_app = get_reviewer_mcp_app()
_planner_mcp_app = get_planner_mcp_app()


@asynccontextmanager
async def lifespan(app):
    """Run MCP sub-app lifespans to initialize their session managers."""
    async with (
        _swe_mcp_app.router.lifespan_context(_swe_mcp_app),
        _reviewer_mcp_app.router.lifespan_context(_reviewer_mcp_app),
        _planner_mcp_app.router.lifespan_context(_planner_mcp_app),
    ):
        yield


app = FastAPI(title="Task Cloud", lifespan=lifespan)
# Starlette middleware stack is LIFO: last added runs first.
# ReviewTypeValidationMiddleware added first, ApiKeyMiddleware second
# → auth check runs before review_type validation.
app.add_middleware(ReviewTypeValidationMiddleware)
app.add_middleware(ApiKeyMiddleware)
templates = Jinja2Templates(directory=find_templates_dir())

# Mount role-based MCP endpoints
app.mount("/mcp-swe", _swe_mcp_app, name="mcp-swe")
app.mount("/mcp-review", _reviewer_mcp_app, name="mcp-review")
app.mount("/mcp-plan", _planner_mcp_app, name="mcp-plan")


@app.get("/health")
async def health():
    """Health check endpoint for Docker HEALTHCHECK."""
    return {"status": "ok", "service": "ralph-tasks"}


class TaskUpdate(BaseModel):
    description: str | None = None
    plan: str | None = None
    report: str | None = None
    blocks: str | None = None
    title: str | None = None
    status: str | None = None


class TaskCreate(BaseModel):
    title: str
    description: str | None = ""
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
            "api_key": _get_configured_api_key(),
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
                    "title": t.title,
                    "status": t.status,
                    "date": date_value[:16],
                }
            )

    tasks_list.sort(key=lambda x: x["date"], reverse=True)
    return {"month": month, "tasks": tasks_list}


@app.get("/kanban/{name}", response_class=HTMLResponse)
async def kanban_board(request: Request, name: str):
    """Display tasks as a kanban board."""
    canonical = normalize_project_name(name)
    if canonical != name:
        redirect_url = f"/kanban/{canonical}"
        if request.url.query:
            redirect_url += f"?{request.url.query}"
        return RedirectResponse(url=redirect_url, status_code=301)
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
            "api_key": _get_configured_api_key(),
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
    """Update task fields."""
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
    name = normalize_project_name(data.name)
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
    if not data.title.strip():
        raise HTTPException(status_code=400, detail="Task title is required")

    task = _create_task(
        project, data.title.strip(), description=data.description or "", plan=data.plan or ""
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
async def upload_attachment_endpoint(
    request: Request,
    project: str,
    number: int,
    file: UploadFile = File(...),  # noqa: B008
):
    """Upload an attachment to a task."""
    _require_task_or_404(project, number)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    max_bytes = _get_max_upload_bytes()

    # Quick reject via Content-Length header (if provided)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
        if declared_size > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"File too large (max {max_mb} MB)")

    # Chunked read with size enforcement
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"File too large (max {max_mb} MB)")
        chunks.append(chunk)

    content = b"".join(chunks)
    result = save_attachment(project, number, file.filename, content)
    return {"ok": True, **result}


@app.get("/api/task/{project}/{number}/attachments/{filename:path}")
async def download_attachment_endpoint(project: str, number: int, filename: str):
    """Download an attachment from MinIO as a streaming response."""
    try:
        content = get_attachment_bytes(project, number, filename)
    except ValueError:
        content = None
    if content is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    safe_name = storage.sanitize_filename(filename)
    # ASCII-safe fallback + RFC 5987 encoding for non-ASCII filenames
    ascii_name = safe_name.encode("ascii", "replace").decode("ascii").replace('"', '\\"')
    disposition = f'attachment; filename="{ascii_name}"'
    # Add filename* for non-ASCII (RFC 5987)
    try:
        safe_name.encode("ascii")
    except UnicodeEncodeError:
        disposition += f"; filename*=UTF-8''{quote(safe_name)}"

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@app.delete("/api/task/{project}/{number}/attachments/{filename:path}")
async def delete_attachment_endpoint(project: str, number: int, filename: str):
    """Delete an attachment."""
    try:
        found = delete_attachment(project, number, filename)
    except ValueError:
        found = False
    if not found:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {"ok": True}


def main():
    """Entry point for the web server."""
    if "--version" in sys.argv:
        print(f"ralph-tasks-web {__version__}")
        sys.exit(0)
    host = os.environ.get("RALPH_TASKS_HOST", "127.0.0.1")
    port = int(os.environ.get("RALPH_TASKS_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
