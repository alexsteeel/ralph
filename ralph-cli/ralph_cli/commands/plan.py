"""Plan command - interactive task planning."""

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, InvalidResponse

from ..config import Settings, get_settings
from ..executor import expand_task_ranges
from ..git import cleanup_working_dir, get_current_branch, get_files_to_clean
from ..logging import SessionLog, format_duration
from ..metrics import submit_session_metrics
from ..prompts import load_prompt

console = Console()

_YES = {"y", "yes", "да", "д", "1", "true"}
_NO = {"n", "no", "нет", "н", "0", "false"}


class FlexibleConfirm(Confirm):
    """Confirm prompt that accepts yes/no/да/нет and other common variants."""

    def process_response(self, value: str) -> bool:
        v = value.strip().lower()
        if v in _YES:
            return True
        if v in _NO:
            return False
        raise InvalidResponse(self.validate_error_message)


def run_codex_plan_review(
    task_ref: str,
    project: str,
    task_number: int,
    working_dir: Path,
    log_dir: Path,
    settings: Settings,
    session_log: SessionLog,
) -> bool:
    """Run interactive Codex plan review.

    Launches Codex TUI with a pre-built prompt. User interacts directly.
    No pipes — Codex writes to terminal like Claude does.
    Findings are printed to terminal (not saved to DB).

    Returns True if codex ran successfully (or was skipped), False on failure.
    """
    if not settings.codex_plan_review_enabled:
        session_log.append("Codex plan review: disabled")
        return True

    if not shutil.which("codex"):
        console.print("[yellow]Codex not found in PATH, skipping plan review[/yellow]")
        session_log.append("Codex plan review: codex not found in PATH")
        return True

    try:
        prompt = load_prompt("codex-plan-reviewer", project=project, number=str(task_number))
    except (FileNotFoundError, KeyError) as e:
        console.print(f"[yellow]Codex plan review prompt unavailable, skipping: {e}[/yellow]")
        session_log.append(f"Codex plan review: prompt load error: {e}")
        return True

    cmd = ["codex", prompt]

    session_log.append(f"Codex plan review started: {task_ref}")
    start_time = time.time()

    try:
        result = subprocess.run(cmd, cwd=working_dir)

        duration = int(time.time() - start_time)
        formatted = format_duration(duration)

        if result.returncode != 0:
            console.print(
                f"[red]✗ Codex plan review failed (exit {result.returncode}, {formatted})[/red]"
            )
            session_log.append(f"Codex plan review failed: exit {result.returncode} ({formatted})")
            return False

        console.print(f"[green]✓ Codex plan review done ({formatted})[/green]")
        session_log.append(f"Codex plan review done ({formatted})")
        return True

    except Exception as e:
        console.print(f"[red]Codex plan review error: {e}[/red]")
        session_log.append(f"Codex plan review error: {e}")
        return False


def run_plan(
    project: str,
    task_args: list[str],
    working_dir: Path | None = None,
) -> int:
    """Run interactive planning for tasks."""
    settings = get_settings()
    tasks = expand_task_ranges(task_args)

    if not tasks:
        console.print("[red]No valid task numbers provided[/red]")
        return 1

    if working_dir is None:
        working_dir = Path.cwd()

    # Setup logging
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.log_dir / "ralph-plan"
    log_dir.mkdir(parents=True, exist_ok=True)
    # Include project and task range in log name for easy identification
    task_range = f"{tasks[0]}" if len(tasks) == 1 else f"{tasks[0]}-{tasks[-1]}"
    session_log = SessionLog(log_dir / f"{project}_{task_range}_{ts}.log")

    session_log.write_header(
        "RALPH PLANNING SESSION",
        Project=project,
        Tasks=", ".join(str(t) for t in tasks),
        WorkingDir=str(working_dir),
    )

    console.rule(f"[bold blue]Ralph Planning: {project}[/bold blue]")
    console.print(f"Tasks: [green]{', '.join(str(t) for t in tasks)}[/green]")
    console.print(f"Working directory: [green]{working_dir}[/green]")

    # Check if on protected branch
    current_branch = get_current_branch(working_dir)
    if current_branch in ("master", "main"):
        console.print(f"\n[bold red]Warning: You are on '{current_branch}' branch![/bold red]")
        if not FlexibleConfirm.ask(
            "[yellow]Are you sure you want to continue?[/yellow]", default=False
        ):
            console.print("[yellow]Pipeline stopped.[/yellow]")
            session_log.append(f"Pipeline stopped: user declined to continue on {current_branch}")
            return 1

    completed = []
    failed = []
    start_time = datetime.now()

    for task_num in tasks:
        task_ref = f"{project}#{task_num}"
        console.rule(f"[cyan]Planning: {task_ref}[/cyan]")
        session_log.append(f"Starting: {task_ref}")

        # Check for uncommitted changes
        modified, untracked = get_files_to_clean(working_dir)
        if modified or untracked:
            total = len(modified) + len(untracked)
            console.print(f"\n[yellow]Found {total} uncommitted files:[/yellow]")

            if modified:
                console.print("[red]Modified:[/red]")
                for f in modified:
                    console.print(f"  [red]M[/red] {f}")

            if untracked:
                console.print("[green]Untracked:[/green]")
                for f in untracked:
                    console.print(f"  [green]?[/green] {f}")

            console.print()
            if not FlexibleConfirm.ask("[yellow]Delete these files?[/yellow]", default=False):
                console.print(
                    "\n[red]Pipeline stopped.[/red]\n"
                    "[yellow]Commit or stash your changes before running ralph plan.[/yellow]"
                )
                session_log.append(
                    "Pipeline stopped: uncommitted changes not confirmed for deletion"
                )
                return 1

            # Cleanup confirmed
            cleaned = cleanup_working_dir(working_dir)
            console.print(f"[dim]Cleaned {len(cleaned)} files[/dim]")
            session_log.append(f"Cleaned {len(cleaned)} files")

        # Run Claude interactively (no pipe - Claude writes directly to tty)
        #
        # ⚠️  WARNING: DO NOT add pipes or redirect stdout/stderr!
        # Claude CLI in interactive mode writes directly to /dev/tty, bypassing stdout.
        # Adding any redirection will block tty output and make terminal appear frozen.
        #
        cmd = [
            "claude",
            "--model",
            "opus",
            "--dangerously-skip-permissions",
            "--settings",
            '{"outputStyle": "explanatory"}',
            f"/ralph-plan-task {task_ref}",  # prompt as last argument, no -p flag
        ]

        try:
            result = subprocess.run(cmd, cwd=working_dir)

            if result.returncode == 0:
                console.print(f"[green]✓ Completed: {task_ref}[/green]")
                session_log.append(f"Completed: {task_ref}")
                completed.append(task_num)

                # Run Codex plan review (interactive)
                if FlexibleConfirm.ask("[cyan]Run Codex plan review?[/cyan]", default=False):
                    run_codex_plan_review(
                        task_ref=task_ref,
                        project=project,
                        task_number=task_num,
                        working_dir=working_dir,
                        log_dir=log_dir,
                        settings=settings,
                        session_log=session_log,
                    )
                else:
                    session_log.append("Codex plan review: skipped by user")
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
        command_type="plan",
        project=project,
        started_at=start_time,
        finished_at=datetime.now(),
        exit_code=0 if not failed else 1,
    )

    return 0 if not failed else 1
