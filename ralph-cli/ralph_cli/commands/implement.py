"""Implement command - autonomous task implementation."""

import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console

from ..config import Settings, get_settings
from ..errors import ErrorType
from ..executor import TaskResult, build_prompt, expand_task_ranges, run_claude
from ..git import cleanup_working_dir, get_head_commit
from ..logging import SessionLog, format_duration
from ..metrics import submit_session_metrics
from ..notify import Notifier
from ..recovery import recovery_loop, should_recover, should_retry_fresh

logger = logging.getLogger(__name__)
console = Console()


def get_project_stats(project: str) -> dict[str, int]:
    """Get task status counts from project via ralph_tasks.core.

    Returns dict like {'done': 5, 'work': 1, 'hold': 0, 'todo': 3}
    """
    try:
        from ralph_tasks.core import list_tasks

        tasks = list_tasks(project)
        stats: dict[str, int] = {}
        for task in tasks:
            stats[task.status] = stats.get(task.status, 0) + 1
        return stats
    except Exception:
        logger.debug("Failed to get project stats for %s", project, exc_info=True)
        return {}


def get_task_status(project: str, task_num: int) -> str | None:
    """Get status of a specific task via ralph_tasks.core.

    Returns status string ('done', 'work', 'hold', 'todo', etc.) or None.
    """
    try:
        from ralph_tasks.core import get_task

        task = get_task(project, task_num)
        return task.status if task else None
    except Exception:
        logger.debug("Failed to get task status for %s#%d", project, task_num, exc_info=True)
        return None


def run_implement(
    project: str,
    task_args: list[str],
    working_dir: Path | None = None,
    extra_prompt: str | None = None,
) -> int:
    """Run autonomous implementation for tasks."""
    settings = get_settings()

    tasks = expand_task_ranges(task_args)

    if not tasks:
        console.print("[red]No valid task numbers provided[/red]")
        return 1

    if working_dir is None:
        working_dir = Path.cwd()

    notifier = Notifier()

    # Setup logging
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.log_dir / "ralph-implement"
    log_dir.mkdir(parents=True, exist_ok=True)
    session_log = SessionLog(log_dir / f"session_{ts}.log")

    session_log.write_header(
        "RALPH IMPLEMENTATION SESSION",
        Project=project,
        Tasks=", ".join(str(t) for t in tasks),
        WorkingDir=str(working_dir),
        Prompt=extra_prompt or "(none)",
    )

    console.rule(f"[bold blue]Ralph Implementation: {project}[/bold blue]")
    console.print(f"Tasks: [green]{', '.join(str(t) for t in tasks)}[/green]")
    console.print(f"Working directory: [green]{working_dir}[/green]")

    # Notify session start
    notifier.session_start(project, tasks)

    completed: list[int] = []
    failed: list[int] = []
    failed_reasons: list[str] = []
    task_durations: dict[int, str] = {}
    task_costs: dict[int, float] = {}
    total_cost: float = 0.0
    pipeline_stopped = False
    start_time = datetime.now()

    for task_num in tasks:
        if pipeline_stopped:
            break

        task_ref = f"{project}#{task_num}"
        console.rule(f"[cyan]Task: {task_ref}[/cyan]")
        session_log.append(f"Starting: {task_ref}")

        # Cleanup before task
        cleaned = cleanup_working_dir(working_dir)
        if cleaned:
            console.print(f"[dim]Cleaned {len(cleaned)} files[/dim]")
            session_log.append(f"Cleaned {len(cleaned)} files")

        # Capture HEAD before task execution for review scope
        base_commit = get_head_commit(working_dir)

        result = execute_task_with_recovery(
            task_ref=task_ref,
            working_dir=working_dir,
            log_dir=log_dir,
            settings=settings,
            notifier=notifier,
            session_log=session_log,
            extra_prompt=extra_prompt,
        )

        task_durations[task_num] = format_duration(result.duration_seconds)
        task_costs[task_num] = result.cost_usd
        total_cost += result.cost_usd

        if result.error_type.is_success:
            console.print(
                f"[green]✓ Completed: {task_ref} ({task_durations[task_num]}, ${result.cost_usd:.2f})[/green]"
            )
            session_log.append(f"Completed: {task_ref}")

            completed.append(task_num)

            # Review chain (after main Claude session completes)
            from .review_chain import run_review_chain

            chain_result = run_review_chain(
                task_ref=task_ref,
                working_dir=working_dir,
                log_dir=settings.log_dir,
                settings=settings,
                session_log=session_log,
                main_session_id=result.session_id,
                notifier=notifier,
                base_commit=base_commit,
            )
            task_costs[task_num] += chain_result.total_cost_usd
            total_cost += chain_result.total_cost_usd

            if chain_result.success:
                console.print("[green]✓ Review Chain: completed[/green]")
            else:
                console.print("[yellow]⚠ Review Chain: finalization failed[/yellow]")

            # Get task status for notification
            task_status = get_task_status(project, task_num)

            # Send task completion notification to Telegram
            notifier.task_complete(
                task_ref=task_ref,
                duration=task_durations[task_num],
                cost_usd=task_costs[task_num],
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                status=task_status,
            )

        elif result.error_type == ErrorType.ON_HOLD:
            console.print(f"[yellow]⚠ On hold: {task_ref}[/yellow]")
            session_log.append(f"On hold: {task_ref}")

        elif result.error_type.is_fatal:
            console.print(f"[red]✗ Fatal error: {task_ref} - {result.error_type.value}[/red]")
            session_log.append(f"Fatal error: {task_ref} - {result.error_type.value}")
            failed.append(task_num)
            failed_reasons.append(result.error_type.value)
            pipeline_stopped = True
            notifier.pipeline_stopped(result.error_type.value)

        else:
            console.print(f"[red]✗ Failed: {task_ref} - {result.error_type.value}[/red]")
            session_log.append(f"Failed: {task_ref} - {result.error_type.value}")
            failed.append(task_num)
            failed_reasons.append(result.error_type.value)
            notifier.task_failed(task_ref, result.error_type.value)

    # Session complete
    duration = format_duration(int((datetime.now() - start_time).total_seconds()))

    session_log.write_summary(
        Completed=[str(t) for t in completed],
        Failed=[f"{t} ({failed_reasons[i]})" for i, t in enumerate(failed)],
    )

    console.rule("[bold blue]Session Complete[/bold blue]")
    console.print(f"Duration: [green]{duration}[/green]")
    console.print(f"Total cost: [green]${total_cost:.2f}[/green]")
    console.print(f"Completed: [green]{len(completed)}[/green]")
    console.print(f"Failed: [red]{len(failed)}[/red]")

    # Get project stats for final report
    project_stats = get_project_stats(project)

    # Notify session complete
    notifier.session_complete(
        project=project,
        duration=duration,
        completed=completed,
        failed=failed,
        failed_reasons=failed_reasons,
        durations=task_durations,
        total_cost_usd=total_cost,
        task_costs=task_costs,
        project_stats=project_stats,
    )

    # Submit metrics (token counts and task_executions not yet available —
    # requires per-task accumulation from StreamMonitor, planned for #86)
    submit_session_metrics(
        command_type="implement",
        project=project,
        started_at=start_time,
        finished_at=datetime.now(),
        total_cost_usd=total_cost,
        exit_code=0 if not failed else 1,
    )

    # Run batch check if any tasks completed
    if completed:
        run_batch_check(project, completed, working_dir, log_dir)

    return 0 if not failed else 1


def execute_task_with_recovery(
    task_ref: str,
    working_dir: Path,
    log_dir: Path,
    settings: Settings,
    notifier: Notifier,
    session_log: SessionLog,
    extra_prompt: str | None = None,
) -> TaskResult:
    """Execute single task with recovery loop."""
    context_overflow_attempts = 0
    resume_session: str | None = None
    recovery_note: str | None = None
    attempt = 0

    while True:
        # Generate unique timestamp for each attempt to avoid overwriting logs
        attempt += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_attempt{attempt}" if attempt > 1 else ""
        log_path = log_dir / f"{task_ref.replace('#', '_')}_{ts}{suffix}.log"

        prompt = build_prompt(
            skill="ralph-implement-python-task",
            task_ref=task_ref,
            recovery_note=recovery_note,
            extra_prompt=extra_prompt,
        )

        result = run_claude(
            prompt=prompt,
            working_dir=working_dir,
            log_path=log_path,
            resume_session=resume_session,
        )

        # Success or on hold - return immediately
        if result.error_type.is_success or result.error_type == ErrorType.ON_HOLD:
            return result

        # Context overflow - retry with fresh session
        if should_retry_fresh(result.error_type, context_overflow_attempts, settings):
            context_overflow_attempts += 1
            notifier.context_overflow(
                task_ref, context_overflow_attempts, settings.context_overflow_max_retries
            )
            session_log.append(
                f"Context overflow retry {context_overflow_attempts}/{settings.context_overflow_max_retries}"
            )
            console.print(
                f"[yellow]Context overflow - retry {context_overflow_attempts}/{settings.context_overflow_max_retries}[/yellow]"
            )
            recovery_note = (
                f"Previous attempt failed with context overflow. "
                f"This is retry {context_overflow_attempts}/{settings.context_overflow_max_retries}. "
                f"Focus on essential changes only."
            )
            resume_session = None
            continue

        # Recoverable error - wait and retry
        if should_recover(result.error_type, settings):
            console.print(
                f"[yellow]API error: {result.error_type.value} - starting recovery[/yellow]"
            )
            session_log.append(f"Recovery started for {result.error_type.value}")

            def on_attempt(attempt: int, max_attempts: int, delay: int):
                notifier.recovery_start(attempt, max_attempts, delay)
                console.print(
                    f"[cyan]Recovery attempt {attempt}/{max_attempts} in {delay // 60} min[/cyan]"
                )

            def on_recovered():
                notifier.recovery_success(task_ref)
                console.print("[green]✓ API recovered[/green]")

            recovered = recovery_loop(
                settings=settings,
                on_attempt=on_attempt,
                on_recovered=on_recovered,
            )

            if recovered:
                session_log.append("API recovered - resuming")
                resume_session = result.session_id
                recovery_note = (
                    f"Previous attempt was interrupted by {result.error_type.value}. "
                    f"This is a recovery resume. Continue where you left off."
                )
                continue
            else:
                session_log.append("Recovery failed - all attempts exhausted")
                console.print("[red]Recovery failed - all attempts exhausted[/red]")
                return result

        # Non-recoverable error
        return result


def run_batch_check(
    project: str,
    completed_tasks: list[int],
    working_dir: Path,
    log_dir: Path,
) -> bool:
    """Run batch check after all tasks complete.

    Returns True if batch check succeeded, False otherwise.
    """
    import subprocess

    console.rule("[cyan]Running batch check[/cyan]")

    task_refs = " ".join(f"{project}#{t}" for t in completed_tasks)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"batch_check_{ts}.log"

    cmd = [
        "claude",
        "-p",
        f"/ralph-batch-check {task_refs}",
        "--model",
        "sonnet",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    try:
        with open(log_path, "w") as log_file:
            from ..monitor import StreamMonitor

            process = subprocess.Popen(
                cmd,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            monitor = StreamMonitor(log_file=log_file)
            if process.stdout:
                monitor.process_stream(process.stdout)

            try:
                return_code = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait()
            monitor.print_summary()

        # Check both process return code and monitor error type
        if return_code != 0:
            console.print(f"[red]✗ Batch check failed (exit code {return_code})[/red]")
            return False

        if not monitor.error_type.is_success:
            console.print(f"[red]✗ Batch check failed: {monitor.error_type.value}[/red]")
            return False

        console.print("[green]✓ Batch check complete[/green]")
        return True

    except Exception as e:
        console.print(f"[red]✗ Batch check failed: {e}[/red]")
        return False
