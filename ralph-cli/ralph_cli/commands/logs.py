"""Logs command - view and manage log files."""

import subprocess
from datetime import datetime
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from ..config import get_settings

console = Console()


class LogType(str, Enum):
    """Log type for filtering."""

    implement = "implement"
    plan = "plan"
    review = "review"
    tests = "tests"
    hooks = "hooks"
    all = "all"


# Mapping from LogType to directory name
LOG_DIRS = {
    LogType.implement: "ralph-implement",
    LogType.plan: "ralph-plan",
    LogType.review: "reviews",
    LogType.tests: "tests",
    LogType.hooks: "hooks",
}


def get_log_files(
    log_type: LogType | None = None,
    task_filter: str | None = None,
) -> list[dict]:
    """Get list of log files with metadata.

    Args:
        log_type: Filter by log type (implement, plan, review, hooks)
        task_filter: Filter by task reference (e.g., "project#1")

    Returns:
        List of dicts with path, type, mtime, size
    """
    settings = get_settings()
    log_dir = settings.log_dir

    # Determine which directories to search
    if log_type and log_type != LogType.all:
        dirs = [log_dir / LOG_DIRS[log_type]]
    else:
        dirs = [log_dir / d for d in LOG_DIRS.values()]

    logs = []

    for d in dirs:
        if not d.exists():
            continue

        for f in d.glob("*.log"):
            # Filter by task if specified
            if task_filter:
                task_safe = task_filter.replace("#", "_")
                if task_safe.lower() not in f.name.lower():
                    continue

            try:
                stat = f.stat()
                logs.append(
                    {
                        "path": f,
                        "type": d.name,
                        "mtime": datetime.fromtimestamp(stat.st_mtime),
                        "size": stat.st_size,
                    }
                )
            except OSError:
                continue

    return logs


def complete_log_files(incomplete: str) -> list[str]:
    """Autocompletion for log file names."""
    logs = get_log_files()

    # Sort by mtime, newest first
    logs.sort(key=lambda x: x["mtime"], reverse=True)

    completions = []
    for log in logs[:50]:  # Limit to 50 most recent
        name = log["path"].name
        if incomplete.lower() in name.lower():
            completions.append(name)

    return completions


def resolve_log_path(path: str) -> Path | None:
    """Resolve log path - can be absolute, relative, or just filename.

    Searches in all log directories if not absolute path.
    """
    log_path = Path(path)

    # If absolute and exists, return it
    if log_path.is_absolute():
        return log_path if log_path.exists() else None

    settings = get_settings()

    # Search in all log directories
    for subdir in LOG_DIRS.values():
        candidate = settings.log_dir / subdir / path
        if candidate.exists():
            return candidate

    # Try as relative to log_dir
    candidate = settings.log_dir / path
    if candidate.exists():
        return candidate

    return None


def list_logs(
    log_type: LogType | None = None,
    task_filter: str | None = None,
    limit: int = 20,
) -> int:
    """List recent log files.

    Args:
        log_type: Filter by type (implement, plan, review, hooks)
        task_filter: Filter by task reference
        limit: Maximum number of logs to show

    Returns:
        Exit code (0 for success)
    """
    logs = get_log_files(log_type, task_filter)

    if not logs:
        if task_filter:
            console.print(f"[yellow]No logs found for task: {task_filter}[/yellow]")
        elif log_type:
            console.print(f"[yellow]No {log_type.value} logs found[/yellow]")
        else:
            console.print("[yellow]No logs found[/yellow]")
        return 0

    # Sort by modification time, newest first
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    logs = logs[:limit]

    # Create table
    title = "Recent Logs"
    if log_type and log_type != LogType.all:
        title = f"Recent {log_type.value.title()} Logs"
    if task_filter:
        title += f" (task: {task_filter})"

    table = Table(title=title)
    table.add_column("#", style="dim", width=3)
    table.add_column("Type", style="cyan", width=16)
    table.add_column("File", style="green")
    table.add_column("Modified", style="yellow", width=16)
    table.add_column("Size", justify="right", width=8)

    for i, log in enumerate(logs, 1):
        size_str = format_size(log["size"])
        time_str = log["mtime"].strftime("%Y-%m-%d %H:%M")
        table.add_row(
            str(i),
            log["type"],
            log["path"].name,
            time_str,
            size_str,
        )

    console.print(table)

    settings = get_settings()
    console.print(f"\n[dim]Log directory: {settings.log_dir}[/dim]")
    console.print("[dim]Use 'ralph logs view <file>' to view contents[/dim]")

    return 0


def view_log(
    path: str,
    lines: int | None = None,
    head: bool = False,
    use_pager: bool | None = None,
    use_vim: bool = False,
    use_editor: bool = False,
) -> int:
    """View log file contents with syntax highlighting.

    Args:
        path: Log file path (absolute, relative, or just filename)
        lines: Number of lines to show (default: all)
        head: If True, show first N lines; if False, show last N lines
        use_pager: None=auto (>50KB), True=force pager, False=no pager
        use_vim: Open in vim
        use_editor: Open in $EDITOR

    Returns:
        Exit code (0 for success, 1 for error)
    """
    import os

    log_path = resolve_log_path(path)

    if not log_path:
        console.print(f"[red]Log file not found: {path}[/red]")
        console.print("[dim]Tip: Use 'ralph logs' to see available logs[/dim]")
        return 1

    # Open in vim
    if use_vim:
        try:
            subprocess.run(["vim", str(log_path)])
            return 0
        except FileNotFoundError:
            console.print("[red]Error: vim not found[/red]")
            return 1

    # Open in $EDITOR
    if use_editor:
        editor = os.environ.get("EDITOR", "vim")
        try:
            subprocess.run([editor, str(log_path)])
            return 0
        except FileNotFoundError:
            console.print(f"[red]Error: {editor} not found[/red]")
            return 1

    try:
        file_size = log_path.stat().st_size
        content = log_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading log: {e}[/red]")
        return 1

    # Limit lines if specified
    if lines:
        content_lines = content.split("\n")
        if head:
            content = "\n".join(content_lines[:lines])
        else:
            content = "\n".join(content_lines[-lines:])

    # Determine if we should use pager
    # Auto: use pager for files > 50KB (unless lines limit makes it small)
    if use_pager is None:
        content_size = len(content.encode("utf-8"))
        use_pager = content_size > 50 * 1024

    # Build header
    header = f"[bold cyan]{log_path}[/bold cyan]\n[dim]Size: {format_size(file_size)}[/dim]\n"

    # Use Syntax for nice display
    syntax = Syntax(
        content,
        "text",
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
    )

    if use_pager:
        # Use system pager (less, more, etc.)
        with console.pager(styles=True):
            console.print(header)
            console.print(syntax)
    else:
        console.print(header)
        console.print(syntax)

    return 0


def tail_log(path: str, lines: int = 50) -> int:
    """Tail log file in real-time.

    Args:
        path: Log file path
        lines: Initial number of lines to show

    Returns:
        Exit code (0 for success, 1 for error)
    """
    log_path = resolve_log_path(path)

    if not log_path:
        console.print(f"[red]Log file not found: {path}[/red]")
        console.print("[dim]Tip: Use 'ralph logs' to see available logs[/dim]")
        return 1

    console.print(f"[bold cyan]Tailing: {log_path}[/bold cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        subprocess.run(["tail", "-f", "-n", str(lines), str(log_path)])
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped[/dim]")
    except FileNotFoundError:
        console.print("[red]Error: 'tail' command not found[/red]")
        return 1

    return 0


def clean_logs(
    log_type: LogType | None = None,
    days: int = 30,
    dry_run: bool = True,
) -> int:
    """Clean old log files.

    Args:
        log_type: Filter by type (None = all types)
        days: Delete logs older than this many days
        dry_run: If True, only show what would be deleted

    Returns:
        Exit code (0 for success)
    """
    from datetime import timedelta

    logs = get_log_files(log_type)
    cutoff = datetime.now() - timedelta(days=days)

    old_logs = [log for log in logs if log["mtime"] < cutoff]

    if not old_logs:
        console.print(f"[green]No logs older than {days} days[/green]")
        return 0

    total_size = sum(log["size"] for log in old_logs)

    if dry_run:
        console.print(
            f"[yellow]Would delete {len(old_logs)} logs ({format_size(total_size)}):[/yellow]"
        )
        for log in old_logs:
            console.print(f"  [dim]{log['path'].name}[/dim]")
        console.print("\n[dim]Use --no-dry-run to actually delete[/dim]")
    else:
        deleted = 0
        for log in old_logs:
            try:
                log["path"].unlink()
                deleted += 1
            except OSError as e:
                console.print(f"[red]Error deleting {log['path'].name}: {e}[/red]")

        console.print(f"[green]Deleted {deleted} logs ({format_size(total_size)})[/green]")

    return 0


def format_size(size: int) -> str:
    """Format file size in human-readable format."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size // 1024} KB"
    else:
        return f"{size // (1024 * 1024)} MB"
