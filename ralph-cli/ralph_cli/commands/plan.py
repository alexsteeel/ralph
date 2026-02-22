"""Plan command - interactive task planning."""

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from ..config import Settings, get_settings
from ..executor import expand_task_ranges
from ..git import cleanup_working_dir, get_current_branch, get_files_to_clean
from ..logging import SessionLog, format_duration

console = Console()

_STREAM_KEYWORDS = ("tool", "exec", "finding", "add_review")


def _build_codex_plan_prompt(project: str, task_number: int) -> str:
    """Build prompt for Codex plan review.

    Instructs Codex to read the task via MCP and validate the plan
    against the body requirements, recording findings via add_review_finding.
    """
    return (
        f"Review the plan for task {project}#{task_number}.\n\n"
        f'1. Read the task using MCP tool: tasks(project="{project}", number={task_number})\n'
        "2. Compare the plan against the body (requirements). Check:\n"
        "   - Completeness: does the plan cover ALL requirements from the body?\n"
        "   - Scope correctness: do referenced files/functions exist?\n"
        "   - Implementation steps: are they realistic and in the right order?\n"
        "   - Testing strategy: is it adequate for the changes?\n"
        "   - Missing edge cases\n"
        "3. For each issue found, call:\n"
        "   add_review_finding(\n"
        f'     project="{project}",\n'
        f"     number={task_number},\n"
        '     review_type="plan",\n'
        '     text="<description of the issue>",\n'
        '     author="codex-plan-reviewer"\n'
        "   )\n"
        "4. If no issues found, do NOT create any findings.\n"
        "5. Do NOT modify any files.\n"
    )


def _check_plan_lgtm(project: str, task_number: int) -> tuple[bool, int | None]:
    """Check if plan review has no open findings (LGTM).

    Returns (is_lgtm, open_findings_count).
    On Neo4j failure returns (True, 0) — cannot verify, treat as passed.
    """
    try:
        from ralph_tasks.core import list_review_findings

        findings = list_review_findings(project, task_number, review_type="plan", status="open")
        return len(findings) == 0, len(findings)
    except Exception as e:
        console.print(f"[yellow]⚠ Cannot verify plan findings (Neo4j unavailable), skipping[/yellow]")
        return True, 0


def run_codex_plan_review(
    task_ref: str,
    project: str,
    task_number: int,
    working_dir: Path,
    log_dir: Path,
    settings: Settings,
    session_log: SessionLog,
) -> tuple[bool, bool]:
    """Run Codex plan review as subprocess.

    Returns (success, is_lgtm):
        - (True, True) if review passed, disabled, or codex not available (graceful skip)
        - (True, False) if review found issues or could not verify findings
        - (False, False) if codex process failed or timed out
    """
    if not settings.codex_plan_review_enabled:
        session_log.append("Codex plan review: disabled")
        return True, True

    if not shutil.which("codex"):
        console.print("[yellow]Codex not found in PATH, skipping plan review[/yellow]")
        session_log.append("Codex plan review: codex not found in PATH")
        return True, True

    prompt = _build_codex_plan_prompt(project, task_number)

    cmd = [
        "codex",
        "exec",
        "--full-auto",
        "-c",
        f'model="{settings.codex_review_model}"',
        "-c",
        'model_reasoning_effort="high"',
        prompt,
    ]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{project}_{task_number}_plan_review_{ts}.log"

    console.print(f"[cyan]Running Codex plan review for {task_ref}...[/cyan]")
    session_log.append(f"Codex plan review started: {task_ref}")
    start_time = time.time()

    try:
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                log_file.write(line)
                text = line.strip()
                if any(kw in text for kw in _STREAM_KEYWORDS):
                    console.print(f"[dim]  {text}[/dim]")
            proc.wait(timeout=settings.review_timeout)

        duration = int(time.time() - start_time)
        formatted_duration = format_duration(duration)

        if proc.returncode != 0:
            console.print(
                f"[red]✗ Codex plan review failed "
                f"(exit {proc.returncode}, {formatted_duration})[/red]"
            )
            session_log.append(
                f"Codex plan review failed: exit code {proc.returncode} ({formatted_duration})"
            )
            return False, False

        # Check whether the review left any open findings
        is_lgtm, open_count = _check_plan_lgtm(project, task_number)

        if is_lgtm:
            console.print(f"[green]Plan review: LGTM ({formatted_duration})[/green]")
            session_log.append(f"Codex plan review: LGTM ({formatted_duration})")
        elif open_count is None:
            console.print(
                f"[yellow]Plan review: could not verify findings ({formatted_duration})[/yellow]"
            )
            session_log.append(
                f"Codex plan review: could not verify findings ({formatted_duration})"
            )
        else:
            console.print(
                f"[yellow]Plan review: {open_count} issue(s) found ({formatted_duration})[/yellow]"
            )
            session_log.append(
                f"Codex plan review: {open_count} issue(s) found ({formatted_duration})"
            )

        return True, is_lgtm

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        console.print(f"[red]Codex plan review timed out after {settings.review_timeout}s[/red]")
        session_log.append(f"Codex plan review timed out after {settings.review_timeout}s")
        return False, False
    except Exception as e:
        console.print(f"[red]Codex plan review error: {e}[/red]")
        session_log.append(f"Codex plan review error: {e}")
        return False, False


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
        if not Confirm.ask("[yellow]Are you sure you want to continue?[/yellow]", default=False):
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
            if not Confirm.ask("[yellow]Delete these files?[/yellow]", default=False):
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
                if Confirm.ask(
                    "[cyan]Run Codex plan review?[/cyan]", default=False
                ):
                    review_success, is_lgtm = run_codex_plan_review(
                        task_ref=task_ref,
                        project=project,
                        task_number=task_num,
                        working_dir=working_dir,
                        log_dir=log_dir,
                        settings=settings,
                        session_log=session_log,
                    )
                    if not review_success:
                        console.print("[yellow]⚠ Codex plan review could not run, skipping[/yellow]")
                    elif not is_lgtm:
                        console.print(
                            "[yellow]⚠ Plan has review issues — "
                            "consider revising before implementation[/yellow]"
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

    return 0 if not failed else 1
