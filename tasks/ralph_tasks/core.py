"""
Core API for ralph-tasks — Neo4j-backed task management.

Provides a clean public API for task/project CRUD operations.
All data is stored in Neo4j graph database.
Attachments are stored in MinIO (S3-compatible object storage).
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neo4j import Session

from minio.error import S3Error
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from ralph_tasks import storage
from ralph_tasks.graph import crud
from ralph_tasks.graph.client import GraphClient
from ralph_tasks.graph.schema import ensure_schema

# Constants
BASE_DIR = Path.home() / ".md-task-mcp"


def normalize_project_name(name: str) -> str:
    """Normalize project name to canonical form (hyphens instead of underscores).

    Strips whitespace and replaces underscores with hyphens.
    """
    return name.strip().replace("_", "-")


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
    f"md-task-mcp core loaded (Neo4j + MinIO). BASE_DIR={BASE_DIR}, uid={os.getuid()}, gid={os.getgid()}"
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
            _migrate_project_names(session)
        _schema_initialized = True


def _migrate_project_names(session: Session) -> None:
    """Rename projects with underscores to canonical hyphenated form.

    Runs once at startup as part of _ensure_graph_ready().
    Skips migration when the canonical name already exists (conflict).
    MinIO prefix migration is best-effort.
    """
    projects = crud.list_projects(session, DEFAULT_WORKSPACE)
    canonical_names = {p["name"] for p in projects}

    for proj in projects:
        name = proj["name"]
        canonical = normalize_project_name(name)
        if canonical == name:
            continue

        if canonical in canonical_names:
            logger.warning(
                f"Cannot migrate project '{name}' -> '{canonical}': "
                "canonical name already exists. Manual merge required."
            )
            continue

        # Migrate MinIO objects first — if this fails, Neo4j still has old name,
        # so attachments remain accessible. Reverse order would orphan objects.
        try:
            storage.migrate_project_prefix(name, canonical)
        except (S3Error, Urllib3HTTPError, OSError) as e:
            logger.warning(f"MinIO migration failed for '{name}' -> '{canonical}': {e}")

        result = crud.rename_project(session, DEFAULT_WORKSPACE, name, canonical)
        if result is None:
            logger.warning(f"Project '{name}' not found during migration, skipping")
            continue
        canonical_names.discard(name)
        canonical_names.add(canonical)
        logger.info(f"Migrated project name: '{name}' -> '{canonical}'")


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
    name = normalize_project_name(name)
    with _session() as session:
        if crud.get_project(session, DEFAULT_WORKSPACE, name) is None:
            crud.create_project(session, DEFAULT_WORKSPACE, name, description)


def project_exists(name: str) -> bool:
    """Check if a project exists."""
    name = normalize_project_name(name)
    with _session() as session:
        return crud.get_project(session, DEFAULT_WORKSPACE, name) is not None


def get_project_description(name: str) -> str:
    """Get project description."""
    name = normalize_project_name(name)
    with _session() as session:
        proj = crud.get_project(session, DEFAULT_WORKSPACE, name)
        return proj["description"] if proj else ""


def set_project_description(name: str, description: str) -> None:
    """Set project description (creates project if needed)."""
    name = normalize_project_name(name)
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
    project = normalize_project_name(project)
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
    project = normalize_project_name(project)
    with _session() as session:
        full = crud.get_task_full(session, project, number)
        if full is None:
            return None
        return _task_from_graph(full)


def list_tasks(project: str) -> list[Task]:
    """List all tasks for a project (summary, no section content)."""
    project = normalize_project_name(project)
    with _session() as session:
        tasks = crud.list_tasks(session, project)
        return [_task_from_graph(t) for t in tasks]


def update_task(project: str, number: int, **fields: Any) -> Task:
    """Update task fields. Handles sections, dependencies, and auto-timestamps.

    Raises ValueError if the task is not found.
    """
    project = normalize_project_name(project)
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
        elif section_updates or new_depends_on is not None:
            # Touch updated_at even when only sections or deps change
            crud.update_task(session, project, number)

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
    """Delete a task and its attachments from Neo4j and MinIO."""
    project = normalize_project_name(project)
    with _session() as session:
        deleted = crud.delete_task(session, project, number)

    if deleted:
        try:
            count = storage.delete_all_objects(project, number)
            if count:
                logger.info(f"Deleted {count} attachments for {project}#{number} from MinIO")
        except (S3Error, Urllib3HTTPError, OSError) as e:
            logger.warning(f"Failed to delete attachments from MinIO for {project}#{number}: {e}")

    return deleted


# ---------------------------------------------------------------------------
# Attachments (MinIO S3 storage)
# ---------------------------------------------------------------------------


def list_attachments(project: str, number: int) -> list[dict]:
    """List all attachments for a task from MinIO."""
    project = normalize_project_name(project)
    return storage.list_objects(project, number)


def save_attachment(project: str, number: int, filename: str, content: bytes) -> dict:
    """Save attachment content to MinIO. For web upload.

    Returns {"name": str, "size": int}.
    """
    project = normalize_project_name(project)
    safe_filename = Path(filename).name
    if not safe_filename:
        raise ValueError("Invalid filename")

    result = storage.put_bytes(project, number, safe_filename, content)
    logger.info(
        f"Saved attachment to MinIO: {project}/{number:03d}/{safe_filename} ({len(content)} bytes)"
    )
    return {"name": result["name"], "size": result["size"]}


def copy_attachment(
    project: str, number: int, source_path: str, filename: str | None = None
) -> dict:
    """Copy a local file to MinIO as task attachment. For MCP.

    Returns {"name": str, "size": int}.
    """
    project = normalize_project_name(project)
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    target_filename = Path(filename).name if filename else source.name
    if not target_filename:
        raise ValueError("Invalid filename")

    content = source.read_bytes()
    result = storage.put_bytes(project, number, target_filename, content)
    logger.info(f"Copied attachment to MinIO: {source} -> {project}/{number:03d}/{target_filename}")
    return {"name": result["name"], "size": result["size"]}


def get_attachment_bytes(project: str, number: int, filename: str) -> bytes | None:
    """Get attachment content from MinIO. Returns None if not found."""
    project = normalize_project_name(project)
    safe_filename = Path(filename).name
    if not safe_filename:
        return None
    return storage.get_object(project, number, safe_filename)


def delete_attachment(project: str, number: int, filename: str) -> bool:
    """Delete an attachment from MinIO. Returns True if deleted."""
    project = normalize_project_name(project)
    safe_filename = Path(filename).name
    if not safe_filename:
        return False
    return storage.delete_object(project, number, safe_filename)
