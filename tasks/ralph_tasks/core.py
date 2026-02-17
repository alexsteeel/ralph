"""
Core API for ralph-tasks — Neo4j-backed task management.

Provides a clean public API for task/project CRUD operations.
All data is stored in Neo4j graph database, except attachments
which remain file-based.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import Session

from ralph_tasks.graph import crud
from ralph_tasks.graph.client import GraphClient
from ralph_tasks.graph.schema import ensure_schema

# Constants
BASE_DIR = Path.home() / ".md-task-mcp"
LOG_FILE = Path("/tmp/md-task-mcp.log")
DEFAULT_WORKSPACE = "default"
VALID_STATUSES = {"todo", "work", "done", "approved", "hold"}

# Section type mapping: Task dataclass field -> Neo4j Section type
_SECTION_FIELDS = {
    "body": "description",
    "plan": "plan",
    "report": "report",
    "review": "review",
    "blocks": "blocks",
}

# Task-level fields stored directly on the Task node
_TASK_NODE_FIELDS = {"description", "status", "module", "branch", "started", "completed"}


# Configure logging
logger = logging.getLogger("md-task-mcp")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    try:
        _handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        _handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(_handler)
    except Exception:
        logger.addHandler(logging.NullHandler())
logger.info(
    f"md-task-mcp core loaded (Neo4j). BASE_DIR={BASE_DIR}, uid={os.getuid()}, gid={os.getgid()}"
)


# Config file
CONFIG_FILE = BASE_DIR / "config.json"


def get_config() -> dict:
    """Read config from config.json."""
    import json

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read config: {e}")
    return {}


def set_config(config: dict) -> None:
    """Write config to config.json."""
    import json

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config saved: {config}")


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """Represents a task stored in Neo4j."""

    number: int
    description: str = ""
    module: str | None = None
    branch: str | None = None
    status: str = "todo"
    started: str | None = None
    completed: str | None = None
    body: str = ""
    plan: str = ""
    report: str = ""
    review: str = ""
    blocks: str = ""
    depends_on: list[int] = field(default_factory=list)
    updated_at: str = ""  # ISO 8601

    def to_dict(self) -> dict:
        """Convert task to dictionary for API responses."""
        return {
            "number": self.number,
            "description": self.description,
            "module": self.module,
            "branch": self.branch,
            "status": self.status,
            "started": self.started,
            "completed": self.completed,
            "body": self.body.strip(),
            "plan": self.plan.strip(),
            "report": self.report.strip(),
            "review": self.review.strip(),
            "blocks": self.blocks.strip(),
            "depends_on": self.depends_on,
            "mtime": _updated_at_to_timestamp(self.updated_at),
        }


def _updated_at_to_timestamp(updated_at: str) -> float:
    """Convert ISO 8601 updated_at to Unix timestamp for backwards compat."""
    if not updated_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(updated_at)
        return dt.timestamp()
    except (ValueError, OSError):
        return 0.0


# ---------------------------------------------------------------------------
# Graph client management (singleton)
# ---------------------------------------------------------------------------

_client: GraphClient | None = None
_schema_initialized: bool = False


def _get_client() -> GraphClient:
    """Get or create the singleton GraphClient."""
    global _client
    if _client is None:
        _client = GraphClient()
    return _client


def _ensure_graph_ready() -> None:
    """Ensure schema is initialized and default workspace exists."""
    global _schema_initialized
    client = _get_client()
    if not _schema_initialized:
        ensure_schema(client)
        with client.session() as session:
            ws = crud.get_workspace(session, DEFAULT_WORKSPACE)
            if ws is None:
                crud.create_workspace(session, DEFAULT_WORKSPACE)
        _schema_initialized = True


def reset_client() -> None:
    """Reset the graph client (for testing)."""
    global _client, _schema_initialized
    if _client is not None:
        _client.close()
    _client = None
    _schema_initialized = False


@contextlib.contextmanager
def _session() -> Generator[Session, None, None]:
    """Ensure graph is ready, then yield a Neo4j session."""
    _ensure_graph_ready()
    with _get_client().session() as session:
        yield session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _task_from_graph(d: dict) -> Task:
    """Convert a graph result dict to Task dataclass.

    Works for both full results (with section_* keys from get_task_full)
    and summary results (from list_tasks, no sections).
    """
    return Task(
        number=d["number"],
        description=d.get("description", ""),
        module=d.get("module"),
        branch=d.get("branch"),
        status=d.get("status", "todo"),
        started=d.get("started"),
        completed=d.get("completed"),
        body=d.get("section_description", ""),
        plan=d.get("section_plan", ""),
        report=d.get("section_report", ""),
        review=d.get("section_review", ""),
        blocks=d.get("section_blocks", ""),
        depends_on=d.get("depends_on", []),
        updated_at=d.get("updated_at", ""),
    )


def _safe_name(name: str) -> str:
    """Sanitize a name for use in filesystem paths (prevent path traversal)."""
    safe = Path(name).name
    if not safe or safe != name:
        raise ValueError(f"Invalid name (contains path separators or is empty): {name!r}")
    return safe


def _get_attachment_dir(project: str, number: int, create: bool = False) -> Path:
    """Get attachment directory: ~/.md-task-mcp/<project>/attachments/<NNN>/"""
    att_dir = BASE_DIR / _safe_name(project) / "attachments" / f"{number:03d}"
    if create:
        att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def list_projects() -> list[str]:
    """List all project names."""
    with _session() as session:
        projects = crud.list_projects(session, DEFAULT_WORKSPACE)
        return [p["name"] for p in projects]


def create_project(name: str, description: str = "") -> None:
    """Create a project under the default workspace."""
    with _session() as session:
        if crud.get_project(session, DEFAULT_WORKSPACE, name) is None:
            crud.create_project(session, DEFAULT_WORKSPACE, name, description)


def project_exists(name: str) -> bool:
    """Check if a project exists."""
    with _session() as session:
        return crud.get_project(session, DEFAULT_WORKSPACE, name) is not None


def get_project_description(name: str) -> str:
    """Get project description."""
    with _session() as session:
        proj = crud.get_project(session, DEFAULT_WORKSPACE, name)
        return proj["description"] if proj else ""


def set_project_description(name: str, description: str) -> None:
    """Set project description (creates project if needed)."""
    with _session() as session:
        proj = crud.get_project(session, DEFAULT_WORKSPACE, name)
        if proj is None:
            crud.create_project(session, DEFAULT_WORKSPACE, name, description)
        else:
            session.run(
                """
                MATCH (w:Workspace {name: $ws})-[:CONTAINS_PROJECT]->(p:Project {name: $name})
                SET p.description = $desc
                """,
                ws=DEFAULT_WORKSPACE,
                name=name,
                desc=description,
            )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def create_task(
    project: str,
    description: str,
    body: str = "",
    plan: str = "",
    **fields: Any,
) -> Task:
    """Create a new task. Auto-creates project if needed.

    Returns the created Task with all fields populated.
    """
    with _session() as session:
        # Ensure project exists
        if crud.get_project(session, DEFAULT_WORKSPACE, project) is None:
            crud.create_project(session, DEFAULT_WORKSPACE, project)

        # Extract task-level fields
        task_fields: dict[str, Any] = {
            key: fields[key]
            for key in ("status", "module", "branch", "started", "completed")
            if fields.get(key) is not None
        }

        task_dict = crud.create_task(session, project, description, **task_fields)
        task_number = task_dict["number"]

        # Create sections for non-empty content
        if body:
            crud.upsert_section(session, project, task_number, "description", body)
        if plan:
            crud.upsert_section(session, project, task_number, "plan", plan)

        # Handle depends_on
        depends_on = fields.get("depends_on")
        if depends_on:
            crud.sync_dependencies(session, project, task_number, depends_on)

        # Re-read full task
        full = crud.get_task_full(session, project, task_number)
        return _task_from_graph(full)


def get_task(project: str, number: int) -> Task | None:
    """Get a task with all sections and dependencies."""
    with _session() as session:
        full = crud.get_task_full(session, project, number)
        if full is None:
            return None
        return _task_from_graph(full)


def list_tasks(project: str) -> list[Task]:
    """List all tasks for a project (summary, no section content)."""
    with _session() as session:
        tasks = crud.list_tasks(session, project)
        return [_task_from_graph(t) for t in tasks]


def update_task(project: str, number: int, **fields: Any) -> Task:
    """Update task fields. Handles sections, dependencies, and auto-timestamps.

    Raises ValueError if the task is not found.
    """
    with _session() as session:
        # Verify task exists
        existing = crud.get_task(session, project, number)
        if existing is None:
            raise ValueError(f"Task #{number} not found in project '{project}'")

        # Separate fields into categories
        task_fields: dict[str, Any] = {}
        section_updates: dict[str, str] = {}
        new_depends_on: list[int] | None = None

        for key, val in fields.items():
            if key in _TASK_NODE_FIELDS:
                task_fields[key] = val
            elif key in _SECTION_FIELDS:
                section_updates[key] = val
            elif key == "depends_on":
                new_depends_on = val

        # Validate status early, before computing auto-timestamps
        new_status = task_fields.get("status")
        if new_status and new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}")

        # Auto-timestamps
        old_status = existing.get("status", "todo")
        if new_status:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            if new_status == "work" and old_status != "work":
                if "started" not in task_fields and not existing.get("started"):
                    task_fields["started"] = now_str
            if new_status in ("done", "approved") and old_status not in ("done", "approved"):
                if "completed" not in task_fields and not existing.get("completed"):
                    task_fields["completed"] = now_str

        # Update task node fields
        if task_fields:
            crud.update_task(session, project, number, **task_fields)

        # Update sections
        for field_name, content in section_updates.items():
            section_type = _SECTION_FIELDS[field_name]
            crud.upsert_section(session, project, number, section_type, content)

        # Update dependencies
        if new_depends_on is not None:
            crud.sync_dependencies(session, project, number, new_depends_on)

        # Re-read and return
        full = crud.get_task_full(session, project, number)
        return _task_from_graph(full)


def delete_task(project: str, number: int) -> bool:
    """Delete a task and its attachments."""
    with _session() as session:
        deleted = crud.delete_task(session, project, number)

    if deleted:
        att_dir = _get_attachment_dir(project, number)
        if att_dir.exists():
            shutil.rmtree(att_dir)
            logger.info(f"Deleted attachments directory: {att_dir}")

    return deleted


# ---------------------------------------------------------------------------
# Attachments (file-based)
# ---------------------------------------------------------------------------


def list_attachments(project: str, number: int) -> list[dict]:
    """List all attachments for a task."""
    att_dir = _get_attachment_dir(project, number)
    if not att_dir.exists():
        return []

    return [
        {"name": f.name, "path": str(f), "size": f.stat().st_size}
        for f in sorted(att_dir.iterdir())
        if f.is_file()
    ]


def save_attachment(project: str, number: int, filename: str, content: bytes) -> dict:
    """Save attachment content to a task. For web upload."""
    att_dir = _get_attachment_dir(project, number, create=True)
    safe_filename = Path(filename).name
    if not safe_filename:
        raise ValueError("Invalid filename")

    file_path = att_dir / safe_filename
    file_path.write_bytes(content)
    logger.info(f"Saved attachment: {file_path} ({len(content)} bytes)")
    return {"name": file_path.name, "path": str(file_path), "size": len(content)}


def copy_attachment(
    project: str, number: int, source_path: str, filename: str | None = None
) -> dict:
    """Copy a file to task attachments. For MCP."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    att_dir = _get_attachment_dir(project, number, create=True)
    target_filename = Path(filename).name if filename else source.name
    if not target_filename:
        raise ValueError("Invalid filename")
    target_path = att_dir / target_filename
    shutil.copy2(source, target_path)
    logger.info(f"Copied attachment: {source} -> {target_path}")
    return {
        "name": target_path.name,
        "path": str(target_path),
        "size": target_path.stat().st_size,
    }


def get_attachment_path(project: str, number: int, filename: str) -> Path | None:
    """Get path to attachment file. Returns None if not found."""
    att_dir = _get_attachment_dir(project, number)
    safe_filename = Path(filename).name
    if not safe_filename:
        return None
    file_path = att_dir / safe_filename
    if file_path.exists() and file_path.is_file():
        return file_path
    return None


def delete_attachment(project: str, number: int, filename: str) -> bool:
    """Delete an attachment. Returns True if deleted, False if not found."""
    file_path = get_attachment_path(project, number, filename)
    if file_path is None:
        return False

    file_path.unlink()
    logger.info(f"Deleted attachment: {file_path}")

    # Remove empty directory
    att_dir = file_path.parent
    if att_dir.exists() and not any(att_dir.iterdir()):
        att_dir.rmdir()
        logger.debug(f"Removed empty attachments directory: {att_dir}")

    return True
