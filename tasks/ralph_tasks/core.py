"""
Core utilities for ralph-tasks.

Shared constants, data classes, and functions used by both
the MCP server and CLI tool.

File structure:
~/.md-task-mcp/
├── project-name/
│   └── tasks/
│       ├── 001-add-user-auth.md
│       ├── 002-fix-login-bug.md
│       └── ...

Each task file format:
# Task {N}: {description}
status: todo|work|done
worktree: /optional/path
started: YYYY-MM-DD HH:MM
completed: YYYY-MM-DD HH:MM

## Description
Task description here.

## Plan
Implementation plan here.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Constants
BASE_DIR = Path.home() / ".md-task-mcp"
LOG_FILE = Path("/tmp/md-task-mcp.log")

# Configure logging
def _setup_logging() -> logging.Logger:
    """Setup logging to file in /tmp/md-task-mcp.log"""
    logger = logging.getLogger("md-task-mcp")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        try:
            handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            logger.addHandler(handler)
        except Exception:
            # Fallback to NullHandler if can't write log
            logger.addHandler(logging.NullHandler())
    return logger

logger = _setup_logging()
logger.info(f"md-task-mcp core loaded. BASE_DIR={BASE_DIR}, uid={os.getuid()}, gid={os.getgid()}")

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


def get_backup_path() -> Path | None:
    """Get backup path from config."""
    config = get_config()
    path = config.get("backup_path")
    return Path(path) if path else None


def set_backup_path(path: str | None) -> None:
    """Set backup path in config."""
    config = get_config()
    if path:
        config["backup_path"] = path
    elif "backup_path" in config:
        del config["backup_path"]
    set_config(config)


VALID_STATUSES = {"todo", "work", "done", "approved", "hold"}


@dataclass
class Task:
    """Represents a task (one file per task)."""

    number: int
    description: str = ""
    module: str | None = None
    branch: str | None = None
    status: str = "todo"
    started: str | None = None
    completed: str | None = None
    body: str = ""  # Description section content
    plan: str = ""  # Plan section content
    report: str = ""  # Report section content
    review: str = ""  # Review section content
    blocks: str = ""  # Blocks section content (what's blocking this task)
    depends_on: list[int] = field(default_factory=list)  # Task dependencies
    file_path: Path | None = field(default=None, repr=False)
    mtime: float = 0.0  # File modification time (Unix timestamp)

    def to_dict(self) -> dict:
        """Convert task to dictionary."""
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
            "mtime": self.mtime,
        }


def ensure_base_dir() -> Path:
    """Create base directory if it doesn't exist."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    return BASE_DIR


def get_project_dir(project: str, create: bool = False) -> Path:
    """Get project directory path, optionally creating it."""
    project_dir = BASE_DIR / project
    if create:
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "tasks").mkdir(exist_ok=True)
    return project_dir


def get_tasks_dir(project: str, create: bool = False) -> Path:
    """Get tasks directory for a project."""
    project_dir = get_project_dir(project, create=create)
    tasks_dir = project_dir / "tasks"
    if create:
        tasks_dir.mkdir(exist_ok=True)
    return tasks_dir


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:50].strip("-")


def get_task_filename(number: int, description: str) -> str:
    """Generate task filename: NNN-slug.md"""
    slug = slugify(description) or "untitled"
    return f"{number:03d}-{slug}.md"


def parse_task_file(path: Path) -> Task | None:
    """
    Parse a single task file into a Task object.

    Format:
    # Task {N}: {description}
    status: todo|work|done
    worktree: /optional/path
    started: YYYY-MM-DD HH:MM
    completed: YYYY-MM-DD HH:MM

    ## Description
    Task description here.

    ## Plan
    Implementation plan here.
    """
    if not path.exists():
        return None

    # Get file modification time
    file_mtime = path.stat().st_mtime

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Parse header: # Task {N}: {description}
    header_pattern = re.compile(r"^#\s+Task\s+(\d+):\s*(.*)$")
    metadata_pattern = re.compile(r"^(\w+):\s*(.*)$")

    task: Task | None = None
    current_section: str | None = None  # None, "description", "plan", "report"
    section_content: list[str] = []

    # Section order - defines valid transitions
    # After blocks, no more sections can start (blocks is the last section)
    section_order = ["description", "plan", "report", "review", "blocks"]

    def get_section_index(section: str | None) -> int:
        """Get the index of a section in the order, -1 if None."""
        if section is None:
            return -1
        return section_order.index(section) if section in section_order else -1

    def can_transition_to(new_section: str) -> bool:
        """Check if we can transition from current_section to new_section."""
        current_idx = get_section_index(current_section)
        new_idx = get_section_index(new_section)
        # Can only transition to a section that comes after current
        return new_idx > current_idx

    def save_section():
        if task and current_section and section_content is not None:
            content = "\n".join(section_content).strip()
            # Unescape section headers in content
            content = _unescape_section_headers(content)
            if current_section == "description":
                task.body = content
            elif current_section == "plan":
                task.plan = content
            elif current_section == "report":
                task.report = content
            elif current_section == "review":
                task.review = content
            elif current_section == "blocks":
                task.blocks = content

    for line in lines:
        # Check for task header
        header_match = header_pattern.match(line)
        if header_match:
            task = Task(
                number=int(header_match.group(1)),
                description=header_match.group(2).strip(),
                file_path=path,
                mtime=file_mtime,
            )
            continue

        if task is None:
            continue

        # Check for section headers (valid only in correct order)
        line_lower = line.strip().lower()

        # Try to match section headers
        section_name = None
        if line_lower == "## description":
            section_name = "description"
        elif line_lower == "## plan":
            section_name = "plan"
        elif line_lower == "## report":
            section_name = "report"
        elif line_lower == "## review":
            section_name = "review"
        elif line_lower == "## blocks":
            section_name = "blocks"

        # Section header is valid only if it follows the correct order
        # This prevents "## Blocks" inside review content from being parsed as section
        # (unless it's escaped with zero-width space during write)
        if section_name and can_transition_to(section_name):
            save_section()
            current_section = section_name
            section_content = []
            continue

        # Check for metadata (only before sections)
        if current_section is None:
            metadata_match = metadata_pattern.match(line)
            if metadata_match:
                key = metadata_match.group(1).lower()
                value = metadata_match.group(2).strip()
                if key == "status":
                    task.status = value if value in VALID_STATUSES else "todo"
                elif key == "module":
                    task.module = value if value else None
                elif key == "branch":
                    task.branch = value if value else None
                elif key == "started":
                    task.started = value if value else None
                elif key == "completed":
                    task.completed = value if value else None
                elif key == "depends_on":
                    if value:
                        task.depends_on = [
                            int(x.strip()) for x in value.split(",")
                            if x.strip().isdigit()
                        ]
        # Collect section content
        if current_section is not None:
            section_content.append(line)

    # Save last section
    save_section()

    return task


def list_tasks(project: str) -> list[Task]:
    """List all tasks for a project by reading individual task files."""
    tasks_dir = get_tasks_dir(project)
    if not tasks_dir.exists():
        return []

    tasks: list[Task] = []
    for task_file in sorted(tasks_dir.glob("*.md")):
        task = parse_task_file(task_file)
        if task:
            tasks.append(task)

    return sorted(tasks, key=lambda t: t.number)


def find_task_file(project: str, task_number: int) -> Path | None:
    """Find existing task file by number."""
    tasks_dir = get_tasks_dir(project)
    if not tasks_dir.exists():
        return None

    pattern = f"{task_number:03d}-*.md"
    matches = list(tasks_dir.glob(pattern))
    return matches[0] if matches else None


def read_task(project: str, task_number: int) -> Task | None:
    """Read a specific task by number."""
    task_file = find_task_file(project, task_number)
    if task_file is None:
        logger.debug(f"Task #{task_number} not found in project '{project}'")
        return None
    logger.debug(f"Reading task #{task_number} from {task_file}")
    return parse_task_file(task_file)


def list_projects() -> list[str]:
    """List all project names."""
    if not BASE_DIR.exists():
        return []

    return sorted([
        d.name
        for d in BASE_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])


def get_project_description(project: str) -> str:
    """Get project description from README.md."""
    readme_path = get_project_dir(project) / "README.md"
    if readme_path.exists():
        return readme_path.read_text(encoding="utf-8").strip()
    return ""


def set_project_description(project: str, description: str) -> None:
    """Set project description in README.md."""
    project_dir = get_project_dir(project, create=True)
    readme_path = project_dir / "README.md"
    readme_path.write_text(description.strip(), encoding="utf-8")


# Section headers that need escaping in content
_SECTION_HEADERS = {"## description", "## plan", "## report", "## review", "## blocks"}


def _escape_section_headers(content: str) -> str:
    """
    Escape section headers in content to prevent parser confusion.

    Replaces '## Section' with '##​Section' (with zero-width space U+200B)
    only for known section headers at the start of a line.
    """
    if not content:
        return content

    lines = content.split("\n")
    escaped_lines = []
    for line in lines:
        line_lower = line.strip().lower()
        if line_lower in _SECTION_HEADERS:
            # Insert zero-width space after ## to escape
            escaped_lines.append(line.replace("## ", "##\u200b", 1))
        else:
            escaped_lines.append(line)
    return "\n".join(escaped_lines)


def _unescape_section_headers(content: str) -> str:
    """
    Unescape section headers in content.

    Replaces '##​Section' (with zero-width space) back to '## Section'.
    """
    if not content:
        return content
    # Remove zero-width space after ##
    return content.replace("##\u200b", "## ")


def task_to_string(task: Task) -> str:
    """Convert a Task object to markdown string."""
    depends_str = ", ".join(map(str, task.depends_on)) if task.depends_on else ""
    lines = [
        f"# Task {task.number}: {task.description}",
        f"status: {task.status}",
        f"module: {task.module or ''}",
        f"branch: {task.branch or ''}",
        f"started: {task.started or ''}",
        f"completed: {task.completed or ''}",
        f"depends_on: {depends_str}",
        "",
        "## Description",
    ]
    if task.body.strip():
        lines.append(_escape_section_headers(task.body.strip()))
    lines.append("")
    lines.append("## Plan")
    if task.plan.strip():
        lines.append(_escape_section_headers(task.plan.strip()))
    lines.append("")
    lines.append("## Report")
    if task.report.strip():
        lines.append(_escape_section_headers(task.report.strip()))
    lines.append("")
    lines.append("## Review")
    if task.review.strip():
        lines.append(_escape_section_headers(task.review.strip()))
    lines.append("")
    lines.append("## Blocks")
    if task.blocks.strip():
        lines.append(_escape_section_headers(task.blocks.strip()))
    lines.append("")
    return "\n".join(lines)


def write_task(project: str, task: Task) -> Path:
    """Write a task to its file. Returns the file path."""
    tasks_dir = get_tasks_dir(project, create=True)

    # Remove old file if description changed (slug changed)
    old_file = find_task_file(project, task.number)
    new_filename = get_task_filename(task.number, task.description)

    if old_file and old_file.name != new_filename:
        logger.info(f"Removing old file: {old_file} (renamed to {new_filename})")

        # Rename attachments directory if exists
        old_attachments_dir = old_file.parent / old_file.stem
        new_attachments_dir = old_file.parent / Path(new_filename).stem
        if old_attachments_dir.exists() and old_attachments_dir.is_dir():
            try:
                old_attachments_dir.rename(new_attachments_dir)
                logger.info(f"Renamed attachments dir: {old_attachments_dir} -> {new_attachments_dir}")
            except Exception:
                logger.exception(f"Failed to rename attachments dir {old_attachments_dir}")
                raise

        try:
            old_file.unlink()
        except Exception:
            logger.exception(f"Failed to unlink old file {old_file}")
            raise

    # Write new file
    task_path = tasks_dir / new_filename
    logger.debug(f"Writing task #{task.number} to {task_path}")

    # Log file info for debugging permission issues
    if task_path.exists():
        stat = task_path.stat()
        logger.debug(
            f"Existing file: uid={stat.st_uid}, gid={stat.st_gid}, "
            f"mode={oct(stat.st_mode)}, size={stat.st_size}"
        )

    try:
        content = task_to_string(task)
        task_path.write_text(content, encoding="utf-8")
        logger.info(f"Successfully wrote task #{task.number} to {task_path} ({len(content)} bytes)")
    except PermissionError as e:
        logger.error(
            f"PermissionError writing {task_path}: {e}. "
            f"Current user: uid={os.getuid()}, gid={os.getgid()}, groups={os.getgroups()}"
        )
        raise
    except Exception:
        logger.exception(f"Failed to write task #{task.number} to {task_path}")
        raise

    task.file_path = task_path
    return task_path


def get_next_task_number(project: str) -> int:
    """Get the next available task number for a project."""
    tasks = list_tasks(project)
    if not tasks:
        return 1
    return max(t.number for t in tasks) + 1


def delete_task(project: str, task_number: int) -> bool:
    """Delete a task file and its attachments directory. Returns True if deleted, False if not found."""
    task_file = find_task_file(project, task_number)
    if task_file is None:
        logger.debug(f"Task #{task_number} not found in project '{project}' for deletion")
        return False
    try:
        # Delete attachments directory if exists
        attachments_dir = task_file.parent / task_file.stem
        if attachments_dir.exists() and attachments_dir.is_dir():
            shutil.rmtree(attachments_dir)
            logger.info(f"Deleted attachments directory: {attachments_dir}")

        task_file.unlink()
        logger.info(f"Deleted task #{task_number} from {task_file}")
        return True
    except Exception:
        logger.exception(f"Failed to delete task #{task_number} from {task_file}")
        raise


# =============================================================================
# Attachments functions
# =============================================================================


def get_attachments_dir(project: str, task_number: int, create: bool = False) -> Path | None:
    """
    Get attachments directory for a task.

    The attachments directory has the same name as the task file stem.
    E.g., for task file "001-add-auth.md", attachments are in "001-add-auth/".

    Returns None if task doesn't exist.
    """
    task_file = find_task_file(project, task_number)
    if task_file is None:
        return None

    attachments_dir = task_file.parent / task_file.stem
    if create:
        attachments_dir.mkdir(exist_ok=True)
        logger.debug(f"Created attachments directory: {attachments_dir}")

    return attachments_dir


def list_attachments(project: str, task_number: int) -> list[dict]:
    """
    List all attachments for a task.

    Returns list of dicts: [{"name": "file.png", "path": "/full/path", "size": 1234}, ...]
    """
    attachments_dir = get_attachments_dir(project, task_number)
    if attachments_dir is None or not attachments_dir.exists():
        return []

    result = []
    for f in sorted(attachments_dir.iterdir()):
        if f.is_file():
            result.append({
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
            })

    return result


def add_attachment(project: str, task_number: int, filename: str, content: bytes) -> Path:
    """
    Add attachment to a task. Returns path to saved file.

    Creates attachments directory if it doesn't exist.
    """
    attachments_dir = get_attachments_dir(project, task_number, create=True)
    if attachments_dir is None:
        raise ValueError(f"Task #{task_number} not found in project '{project}'")

    # Sanitize filename
    safe_filename = Path(filename).name
    if not safe_filename:
        raise ValueError("Invalid filename")

    file_path = attachments_dir / safe_filename
    file_path.write_bytes(content)
    logger.info(f"Added attachment: {file_path} ({len(content)} bytes)")

    return file_path


def get_attachment_path(project: str, task_number: int, filename: str) -> Path | None:
    """Get path to attachment file. Returns None if not found."""
    attachments_dir = get_attachments_dir(project, task_number)
    if attachments_dir is None:
        return None

    file_path = attachments_dir / filename
    if file_path.exists() and file_path.is_file():
        return file_path

    return None


def delete_attachment(project: str, task_number: int, filename: str) -> bool:
    """Delete an attachment. Returns True if deleted, False if not found."""
    file_path = get_attachment_path(project, task_number, filename)
    if file_path is None:
        return False

    try:
        file_path.unlink()
        logger.info(f"Deleted attachment: {file_path}")

        # Remove empty attachments directory
        attachments_dir = file_path.parent
        if attachments_dir.exists() and not any(attachments_dir.iterdir()):
            attachments_dir.rmdir()
            logger.debug(f"Removed empty attachments directory: {attachments_dir}")

        return True
    except Exception:
        logger.exception(f"Failed to delete attachment: {file_path}")
        raise


def copy_attachment(project: str, task_number: int, source_path: str, filename: str | None = None) -> Path:
    """
    Copy a file to task attachments.

    Args:
        project: Project name
        task_number: Task number
        source_path: Path to source file to copy
        filename: Optional new filename (default: use source filename)

    Returns path to copied file.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    attachments_dir = get_attachments_dir(project, task_number, create=True)
    if attachments_dir is None:
        raise ValueError(f"Task #{task_number} not found in project '{project}'")

    target_filename = filename or source.name
    target_path = attachments_dir / target_filename

    shutil.copy2(source, target_path)
    logger.info(f"Copied attachment: {source} -> {target_path}")

    return target_path
