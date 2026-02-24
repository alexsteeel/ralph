"""Interview command - deep interview to create task specification."""

import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console

from ..config import get_settings
from ..executor import expand_task_ranges
from ..git import get_current_branch
from ..logging import SessionLog, format_duration
from ..metrics import submit_session_metrics

console = Console()


def run_interview(
    project: str,
    task_args: list[str],
    working_dir: Path | None = None,
) -> int:
    """Run deep interview for tasks to create specifications."""
    settings = get_settings()
    tasks = expand_task_ranges(task_args)

    if not tasks:
        console.print("[red]No valid task numbers provided[/red]")
        return 1

    if working_dir is None:
        working_dir = Path.cwd()

    # Setup logging
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.log_dir / "ralph-interview"
    log_dir.mkdir(parents=True, exist_ok=True)
    task_range = f"{tasks[0]}" if len(tasks) == 1 else f"{tasks[0]}-{tasks[-1]}"
    session_log = SessionLog(log_dir / f"{project}_{task_range}_{ts}.log")

    session_log.write_header(
        "RALPH INTERVIEW SESSION",
        Project=project,
        Tasks=", ".join(str(t) for t in tasks),
        WorkingDir=str(working_dir),
    )

    console.rule(f"[bold blue]Ralph Interview: {project}[/bold blue]")
    console.print(f"Tasks: [green]{', '.join(str(t) for t in tasks)}[/green]")
    console.print(f"Working directory: [green]{working_dir}[/green]")

    # Check if on protected branch
    current_branch = get_current_branch(working_dir)
    if current_branch in ("master", "main"):
        console.print(f"\n[bold yellow]Note: You are on '{current_branch}' branch[/bold yellow]")

    completed = []
    failed = []
    start_time = datetime.now()

    for task_num in tasks:
        task_ref = f"{project}#{task_num}"
        console.rule(f"[cyan]Interviewing: {task_ref}[/cyan]")
        session_log.append(f"Starting interview: {task_ref}")

        # Run Claude interactively
        cmd = [
            "claude",
            "--model",
            "opus",
            "--dangerously-skip-permissions",
            f"/ralph-interview-task {task_ref}",
        ]

        try:
            result = subprocess.run(cmd, cwd=working_dir)

            if result.returncode == 0:
                console.print(f"[green]✓ Completed: {task_ref}[/green]")
                session_log.append(f"Completed: {task_ref}")
                completed.append(task_num)
            else:
                console.print(f"[red]✗ Failed: {task_ref} (exit code {result.returncode})[/red]")
                session_log.append(f"Failed: {task_ref} (exit code {result.returncode})")
                failed.append(task_num)

        except KeyboardInterrupt:
            console.print("[yellow]Interrupted by user[/yellow]")
            session_log.append("Session interrupted by user")
            break
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            session_log.append(f"Error: {e}")
            failed.append(task_num)

    # Summary
    duration = format_duration(int((datetime.now() - start_time).total_seconds()))

    session_log.write_summary(
        Completed=[str(t) for t in completed],
        Failed=[str(t) for t in failed],
    )

    console.rule("[bold blue]Session Complete[/bold blue]")
    console.print(f"Duration: [green]{duration}[/green]")
    console.print(f"Completed: [green]{len(completed)}[/green]")
    console.print(f"Failed: [red]{len(failed)}[/red]")

    # Submit metrics (minimal — no cost/tokens in TUI mode)
    submit_session_metrics(
        command_type="interview",
        project=project,
        started_at=start_time,
        finished_at=datetime.now(),
        exit_code=0 if not failed else 1,
    )

    return 0 if not failed else 1
