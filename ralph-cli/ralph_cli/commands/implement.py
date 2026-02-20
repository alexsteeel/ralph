"""Implement command - autonomous task implementation."""

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

from ..config import Settings, get_settings
from ..errors import ErrorType
from ..executor import TaskResult, build_prompt, expand_task_ranges, run_claude
from ..git import cleanup_working_dir
from ..logging import SessionLog, format_duration
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

            # Codex review loop (after main Claude work, resuming same session for fixes)
            codex_ok = run_codex_review_loop(
                task_ref=task_ref,
                working_dir=working_dir,
                log_dir=settings.log_dir / "reviews",
                settings=settings,
                session_log=session_log,
                session_id=result.session_id,
            )
            if codex_ok:
                console.print("[green]✓ Codex Review: LGTM[/green]")
            else:
                console.print("[yellow]⚠ Codex Review: issues remain after max iterations[/yellow]")

            completed.append(task_num)

            # Get task status for notification
            task_status = get_task_status(project, task_num)

            # Send task completion notification to Telegram
            notifier.task_complete(
                task_ref=task_ref,
                duration=task_durations[task_num],
                cost_usd=result.cost_usd,
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


def _build_codex_review_prompt(task_ref: str) -> str:
    """Build prompt for codex review (first iteration only).

    Subsequent iterations use --uncommitted flag without a prompt
    (codex CLI doesn't allow both --uncommitted and a prompt).
    """
    return (
        f"Выполни код-ревью для задачи {task_ref}.\n"
        "\n"
        "1. Получи детали задачи через MCP md-task-mcp: tasks(project, number)\n"
        "2. Прочитай CLAUDE.md для URL/credentials тестового сервера\n"
        "3. Проанализируй последний коммит (git log -1 -p, git diff HEAD~1)\n"
        "4. Если есть frontend — проверь UI через playwright MCP\n"
        "5. ДОБАВЬ результаты к Review: update_task(review=existing + new)\n"
        "\n"
        "Формат замечаний: CRITICAL / HIGH / MEDIUM / LOW\n"
        'Если замечаний нет — напиши "LGTM" в конце.\n'
        "\n"
        "НЕ ИЗМЕНЯЙ КОД — только анализируй."
    )


def _build_claude_fix_prompt(task_ref: str) -> str:
    """Build prompt for claude fix session."""
    return (
        f"Прочитай review поле задачи {task_ref} через md-task-mcp.\n"
        "Исправь все CRITICAL и HIGH замечания от последней итерации Codex Review.\n"
        "\n"
        "Для каждого замечания:\n"
        "- ✅ [main-claude] Fixed: <что исправлено> — если исправил\n"
        "- ❌ [main-claude] Declined: <обоснование> — если некорректно\n"
        "\n"
        "Обнови review поле задачи с отметками.\n"
        "НЕ делай коммит — просто исправь код."
    )


def run_codex_review(
    task_ref: str,
    working_dir: Path,
    log_path: Path,
    iteration: int,
    settings: Settings,
) -> tuple[bool, bool]:
    """Run codex review as subprocess.

    Returns (success, is_lgtm).
    """
    if not shutil.which("codex"):
        console.print("[red]codex not found in PATH[/red]")
        return False, False

    model = settings.codex_review_model

    # First iteration reviews committed code with custom prompt,
    # subsequent ones check uncommitted fixes (--uncommitted is incompatible with prompt)
    if iteration > 1:
        cmd = [
            "codex",
            "review",
            "--uncommitted",
            "-c",
            f'model="{model}"',
            "-c",
            'model_reasoning_effort="high"',
        ]
    else:
        prompt = _build_codex_review_prompt(task_ref)
        cmd = [
            "codex",
            "review",
            "-c",
            f'model="{model}"',
            "-c",
            'model_reasoning_effort="high"',
            prompt,
        ]

    console.print(f"[cyan]Codex review iteration {iteration}...[/cyan]")

    start_time = time.time()
    try:
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            last_status_time = start_time
            line_count = 0
            past_prompt = False
            expect_exec_cmd = False
            codex_output_lines: list[str] = []
            for raw_line in proc.stdout:
                log_file.write(raw_line.decode("utf-8", errors="replace"))
                line_count += 1
                text = raw_line.decode("utf-8", errors="replace").strip()

                # Track when we're past the initial prompt echo
                if not past_prompt and text.startswith("thinking"):
                    past_prompt = True
                if past_prompt:
                    codex_output_lines.append(text)

                # After "exec" line, next line has the command details
                if expect_exec_cmd:
                    expect_exec_cmd = False
                    # Format: '/usr/bin/zsh -lc "cmd..." in /dir succeeded in Xms:'
                    cmd_display = text
                    if '"' in text:
                        # Extract the shell command from between quotes
                        parts = text.split('"', 2)
                        if len(parts) >= 2:
                            cmd_display = parts[1]
                    elapsed = format_duration(int(time.time() - start_time))
                    console.print(f"  [dim][{elapsed}] exec: {cmd_display}[/dim]")
                    last_status_time = time.time()
                    continue

                # Show key events in console
                if text.startswith("tool "):
                    tool_name = text.split("(", 1)[0].replace("tool ", "")
                    elapsed = format_duration(int(time.time() - start_time))
                    console.print(f"  [dim][{elapsed}] tool: {tool_name}[/dim]")
                    last_status_time = time.time()
                elif text == "exec":
                    expect_exec_cmd = True
                elif time.time() - last_status_time >= 60:
                    elapsed = format_duration(int(time.time() - start_time))
                    console.print(f"  [dim][{elapsed}] processing... ({line_count} lines)[/dim]")
                    last_status_time = time.time()

            proc.wait()

        duration = int(time.time() - start_time)

        if proc.returncode != 0:
            console.print(
                f"[red]Codex review failed (exit code {proc.returncode}, {format_duration(duration)})[/red]"
            )
            return False, False

        # Check LGTM only in codex output (after prompt), not in the full log
        # which contains our prompt with the word "LGTM" in instructions
        codex_output = "\n".join(codex_output_lines)
        is_lgtm = "LGTM" in codex_output
        console.print(
            f"[green]Codex review done ({format_duration(duration)})"
            f"{' — LGTM!' if is_lgtm else ''}[/green]"
        )
        return True, is_lgtm

    except Exception as e:
        console.print(f"[red]Codex review error: {e}[/red]")
        return False, False


def run_claude_fix(
    task_ref: str,
    working_dir: Path,
    log_path: Path,
    iteration: int,
    settings: Settings,
    resume_session: str | None = None,
) -> bool:
    """Run claude to fix codex review issues.

    When resume_session is provided, continues the original implementation
    session so Claude has full context of what was done and why.

    Returns True if fix succeeded.
    """
    prompt = _build_claude_fix_prompt(task_ref)

    console.print(
        f"[cyan]Claude fix iteration {iteration}{' (resuming session)' if resume_session else ''}...[/cyan]"
    )

    result = run_claude(
        prompt=prompt,
        working_dir=working_dir,
        log_path=log_path,
        resume_session=resume_session,
    )

    if result.error_type.is_success:
        console.print(
            f"[green]Claude fix done ({format_duration(result.duration_seconds)}, ${result.cost_usd:.2f})[/green]"
        )
        return True

    console.print(f"[red]Claude fix failed: {result.error_type.value}[/red]")
    return False


def run_codex_review_loop(
    task_ref: str,
    working_dir: Path,
    log_dir: Path,
    settings: Settings,
    session_log: SessionLog,
    session_id: str | None = None,
) -> bool:
    """Run iterative codex review loop.

    1. codex review -> writes review to task, outputs to log
    2. Check for LGTM in output -> if yes, done
    3. claude fix (--resume original session) -> fixes issues with full context
    4. Repeat up to max_iterations

    Args:
        session_id: Claude session ID from the main implementation run.
            When provided, fix sessions resume this session so Claude has
            full context of what was implemented and why.

    Returns True if LGTM achieved, False otherwise.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    task_safe = task_ref.replace("#", "_")
    max_iterations = settings.codex_review_max_iterations

    console.rule(f"[cyan]Codex Review Loop: {task_ref}[/cyan]")
    session_log.append(f"Codex review loop started: {task_ref}")

    for iteration in range(1, max_iterations + 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Codex review
        review_log = log_dir / f"{task_safe}_codex-review_iter{iteration}_{ts}.log"
        success, is_lgtm = run_codex_review(
            task_ref=task_ref,
            working_dir=working_dir,
            log_path=review_log,
            iteration=iteration,
            settings=settings,
        )

        if not success:
            session_log.append(f"Codex review failed at iteration {iteration}")
            return False

        if is_lgtm:
            # If there were fixes (iteration > 1), create a fixup commit
            if iteration > 1:
                _create_fixup_commit(task_ref, working_dir, session_log)
            session_log.append(f"Codex LGTM after {iteration} iteration(s)")
            return True

        # 2. Claude fix (not on last iteration)
        if iteration < max_iterations:
            fix_log = log_dir / f"{task_safe}_codex-fix_iter{iteration}_{ts}.log"
            fix_success = run_claude_fix(
                task_ref=task_ref,
                working_dir=working_dir,
                log_path=fix_log,
                iteration=iteration,
                settings=settings,
                resume_session=session_id,
            )
            if not fix_success:
                session_log.append(f"Claude fix failed at iteration {iteration}")
                return False

    # Max iterations without LGTM — commit fixes if any were made
    if max_iterations > 1:
        _create_fixup_commit(task_ref, working_dir, session_log)

    session_log.append(f"Codex review: max iterations ({max_iterations}) reached without LGTM")
    return False


def _create_fixup_commit(
    task_ref: str,
    working_dir: Path,
    session_log: SessionLog,
) -> None:
    """Create a fixup commit for codex review fixes if there are changes."""
    # Check if there are uncommitted changes
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return

    # Get the last commit hash for fixup
    log_result = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    )
    last_hash = log_result.stdout.strip()
    if not last_hash:
        return

    # Stage and create fixup commit
    subprocess.run(["git", "add", "-A"], cwd=working_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", f"--fixup={last_hash}"],
        cwd=working_dir,
        capture_output=True,
    )

    # Autosquash
    subprocess.run(
        ["git", "rebase", "-i", "--autosquash", f"{last_hash}~1"],
        cwd=working_dir,
        capture_output=True,
        env={**subprocess.os.environ, "GIT_SEQUENCE_EDITOR": "true"},
    )

    session_log.append("Created fixup commit for codex review fixes")
    console.print("[dim]Fixup commit created for codex review fixes[/dim]")


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
