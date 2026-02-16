"""Review command - run code reviews in isolated contexts."""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from rich.console import Console
from rich.table import Table

from ..config import Settings, get_settings
from ..logging import format_duration
from ..notify import Notifier

# Env vars that prevent nested Claude Code sessions
_CLAUDE_SESSION_VARS = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}


def _clean_env() -> dict[str, str]:
    """Return env dict without Claude session vars to allow nested launches."""
    return {k: v for k, v in os.environ.items() if k not in _CLAUDE_SESSION_VARS}

console = Console()


class ReviewResult(NamedTuple):
    """Result of a single review."""

    name: str
    success: bool
    duration_seconds: int
    log_path: Path
    log_size: int


# Claude-based reviews (run via claude -p "/command task_ref")
CLAUDE_REVIEWS = [
    ("Code Review (5 agents)", "ralph-review-code"),
    ("Code Simplifier", "ralph-review-simplify"),
    ("Security Review", "ralph-review-security"),
]


def run_review(task_ref: str) -> int:
    """Run all code reviews in isolated contexts."""
    settings = get_settings()
    notifier = Notifier()

    console.rule(f"[bold blue]Running Reviews: {task_ref}[/bold blue]")

    # Setup logging
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.log_dir / "reviews"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Suspend workflow state (if exists)
    state_file = Path.home() / ".claude/workflow-state/active_ralph_task.txt"
    state_backup = state_file.with_suffix(".bak")
    state_suspended = False

    if state_file.exists():
        try:
            state_file.rename(state_backup)
            state_suspended = True
            console.print("[dim]Workflow state suspended[/dim]")
        except Exception as e:
            console.print(f"[yellow]Could not suspend workflow state: {e}[/yellow]")

    results: list[ReviewResult] = []

    try:
        # Run Claude-based reviews
        for review_name, skill_name in CLAUDE_REVIEWS:
            result = run_single_review(
                task_ref=task_ref,
                review_name=review_name,
                skill_name=skill_name,
                log_dir=log_dir,
                timestamp=ts,
                settings=settings,
            )
            results.append(result)

    finally:
        # Restore workflow state
        if state_suspended and state_backup.exists():
            try:
                state_backup.rename(state_file)
                console.print("[dim]Workflow state restored[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not restore workflow state: {e}[/yellow]")

    # Print summary
    print_review_summary(results)

    # Notify about failures
    failed_reviews = [r for r in results if not r.success]
    for r in failed_reviews:
        reason = _detect_failure_reason(r)
        notifier.review_failed(
            task_ref=task_ref,
            review_name=r.name,
            reason=reason,
            log_path=str(r.log_path),
        )

    return 0 if not failed_reviews else 1


def run_single_review(
    task_ref: str,
    review_name: str,
    skill_name: str,
    log_dir: Path,
    timestamp: str,
    settings: Settings,
) -> ReviewResult:
    """Run single review and return result."""
    console.print(f"[cyan]Starting: {review_name}[/cyan]")

    # Build log path
    safe_name = skill_name.replace("-", "_")
    task_safe = task_ref.replace("#", "_")
    log_path = log_dir / f"{task_safe}_{safe_name}_{timestamp}.log"

    cmd = [
        "claude",
        "-p",
        f"/{skill_name} {task_ref}",
        "--model",
        "sonnet",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    start_time = time.time()

    try:
        with open(log_path, "w") as log_file:
            result = subprocess.run(
                cmd,
                env=_clean_env(),
                stdin=subprocess.DEVNULL,  # Prevent hang when running from another Claude session
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=settings.review_timeout,
            )

        duration = int(time.time() - start_time)
        success = result.returncode == 0
        log_size = log_path.stat().st_size

        if success:
            console.print(
                f"[green]✓ Completed: {review_name} ({format_duration(duration)})[/green]"
            )
        else:
            console.print(f"[red]✗ Failed: {review_name} (exit code {result.returncode})[/red]")

        return ReviewResult(
            name=review_name,
            success=success,
            duration_seconds=duration,
            log_path=log_path,
            log_size=log_size,
        )

    except subprocess.TimeoutExpired:
        duration = int(time.time() - start_time)
        console.print(f"[red]✗ Timeout: {review_name}[/red]")
        return ReviewResult(
            name=review_name,
            success=False,
            duration_seconds=duration,
            log_path=log_path,
            log_size=log_path.stat().st_size if log_path.exists() else 0,
        )

    except Exception as e:
        duration = int(time.time() - start_time)
        console.print(f"[red]✗ Error: {review_name} - {e}[/red]")
        return ReviewResult(
            name=review_name,
            success=False,
            duration_seconds=duration,
            log_path=log_path,
            log_size=0,
        )


def _detect_failure_reason(result: ReviewResult) -> str:
    """Detect failure reason from review log file."""
    if not result.log_path.exists() or result.log_size == 0:
        return "No output (process crashed or not found)"

    try:
        # Read last 2KB of log for error detection
        with open(result.log_path, errors="replace") as f:
            f.seek(max(0, result.log_size - 2048))
            tail = f.read()
    except Exception:
        return "Could not read log file"

    tail_lower = tail.lower()

    if ("rate" in tail_lower and "limit" in tail_lower) or "429" in tail:
        return "Rate limit (429)"
    if "quota" in tail_lower or "billing" in tail_lower or "insufficient" in tail_lower:
        return "Quota/billing limit exceeded"
    if "timeout" in tail_lower or "timed out" in tail_lower:
        return "Request timeout"
    if (
        "401" in tail
        or "unauthorized" in tail_lower
        or ("auth" in tail_lower and "fail" in tail_lower)
    ):
        return "Authentication error (401)"
    if "403" in tail or "forbidden" in tail_lower:
        return "Forbidden (403)"
    if "529" in tail or "overloaded" in tail_lower:
        return "API overloaded (529)"
    if "connection" in tail_lower and (
        "refused" in tail_lower or "error" in tail_lower or "reset" in tail_lower
    ):
        return "Connection error"

    return "Exit code non-zero (see log)"


def print_review_summary(results: list[ReviewResult]):
    """Print summary table of review results."""
    success_count = sum(1 for r in results if r.success)
    total = len(results)

    console.rule("[bold blue]SUMMARY[/bold blue]")

    if success_count == total:
        console.print(f"[green]✓ All {total}/{total} reviews completed successfully![/green]")
    else:
        console.print(f"[yellow]⚠ {success_count}/{total} reviews completed[/yellow]")

    # Create table
    table = Table()
    table.add_column("Review", style="cyan")
    table.add_column("Status")
    table.add_column("Time", justify="center")
    table.add_column("Log Size", justify="right")

    for r in results:
        status = "[green]✓ Completed[/green]" if r.success else "[red]✗ Failed[/red]"
        time_str = format_duration(r.duration_seconds)[:5]
        size_kb = f"{r.log_size // 1024} KB"
        table.add_row(r.name, status, time_str, size_kb)

    console.print(table)

    # Print log file paths
    console.print("\n[dim]Log files:[/dim]")
    for r in results:
        console.print(f"  {r.name}: {r.log_path}")
