"""Review chain orchestration — all review phases after main implementation."""

import concurrent.futures
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console

from ..config import Settings
from ..executor import run_claude
from ..logging import SessionLog, format_duration
from ..notify import Notifier
from ..prompts import load_prompt

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class ReviewChainContext:
    """Shared state for review chain execution."""

    task_ref: str
    project: str
    task_number: int
    working_dir: Path
    log_dir: Path
    settings: Settings
    session_log: SessionLog
    notifier: Notifier
    main_session_id: str | None = None
    base_commit: str | None = None
    review_session_ids: dict[str, str | None] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class ReviewPhaseResult:
    """Result of a single review phase."""

    success: bool
    lgtm: bool = True
    cost_usd: float = 0.0
    findings_count: int = 0
    error: str | None = None


# Code review agent definitions: (prompt_name, section_type)
CODE_REVIEW_AGENTS = [
    ("code-reviewer", "code-review"),
    ("comment-analyzer", "comment-analysis"),
    ("pr-test-analyzer", "pr-test-analysis"),
    ("silent-failure-hunter", "silent-failure-hunting"),
]

CODE_REVIEW_SECTION_TYPES = [section for _, section in CODE_REVIEW_AGENTS]


def _parse_task_ref(task_ref: str) -> tuple[str, int]:
    """Parse 'project#N' into (project, N)."""
    project, num_str = task_ref.split("#", 1)
    return project, int(num_str)


def _log_path(ctx: ReviewChainContext, name: str, suffix: str = "") -> Path:
    """Generate log path for a review step."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_safe = ctx.task_ref.replace("#", "_")
    return ctx.log_dir / f"{task_safe}_{name}{suffix}_{ts}.log"


# ---------------------------------------------------------------------------
# LGTM checking via Neo4j
# ---------------------------------------------------------------------------


def check_lgtm(project: str, task_number: int, section_types: list[str]) -> tuple[bool, int]:
    """Check if all findings are resolved/declined (LGTM).

    Returns (is_lgtm, open_findings_count).
    """
    try:
        from ralph_tasks.core import list_review_findings

        findings = list_review_findings(project, task_number, status="open")
        open_count = sum(1 for f in findings if f.get("section_type") in section_types)
        return open_count == 0, open_count
    except Exception as e:
        logger.warning("Failed to check LGTM: %s", e)
        return False, -1


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def create_fixup_commit(
    working_dir: Path,
    session_log: SessionLog,
    message: str = "review fixes",
) -> None:
    """Create fixup commit and autosquash if there are changes."""
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return

    log_result = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        cwd=working_dir,
        capture_output=True,
        text=True,
    )
    last_hash = log_result.stdout.strip()
    if not last_hash:
        return

    subprocess.run(["git", "add", "-A"], cwd=working_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", f"--fixup={last_hash}"],
        cwd=working_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "rebase", "-i", "--autosquash", f"{last_hash}~1"],
        cwd=working_dir,
        capture_output=True,
        env={**os.environ, "GIT_SEQUENCE_EDITOR": "true"},
    )

    session_log.append(f"Created fixup commit for {message}")
    console.print(f"[dim]Fixup commit created for {message}[/dim]")


# ---------------------------------------------------------------------------
# Fix session (resume main to address findings)
# ---------------------------------------------------------------------------


def run_fix_session(
    ctx: ReviewChainContext,
    section_types: list[str],
    iteration: int,
) -> bool:
    """Resume main session to fix review findings. Returns True if succeeded."""
    prompt = load_prompt(
        "fix-review-issues",
        task_ref=ctx.task_ref,
        project=ctx.project,
        number=str(ctx.task_number),
        section_types=", ".join(section_types),
    )

    log_path = _log_path(ctx, "fix", f"_iter{iteration}")

    console.print(
        f"[cyan]Fix session iteration {iteration}"
        f"{' (resuming)' if ctx.main_session_id else ''}...[/cyan]"
    )

    result = run_claude(
        prompt=prompt,
        working_dir=ctx.working_dir,
        log_path=log_path,
        resume_session=ctx.main_session_id,
    )

    if result.error_type.is_success:
        console.print(
            f"[green]Fix done ({format_duration(result.duration_seconds)}, "
            f"${result.cost_usd:.2f})[/green]"
        )
        return True

    console.print(f"[red]Fix failed: {result.error_type.value}[/red]")
    return False


# ---------------------------------------------------------------------------
# Single review agent execution
# ---------------------------------------------------------------------------


def run_single_review_agent(
    ctx: ReviewChainContext,
    agent_name: str,
    section_type: str,
) -> tuple[bool, str | None]:
    """Run a single review agent as a Claude session.

    Returns (success, session_id).
    """
    try:
        prompt = load_prompt(
            agent_name,
            task_ref=ctx.task_ref,
            project=ctx.project,
            number=str(ctx.task_number),
            base_commit=ctx.base_commit or "",
        )
    except FileNotFoundError as e:
        logger.error("Prompt not found: %s", e)
        return False, None

    log_path = _log_path(ctx, agent_name)

    result = run_claude(
        prompt=prompt,
        working_dir=ctx.working_dir,
        log_path=log_path,
        model=ctx.settings.claude_review_model,
    )

    if result.error_type.is_success:
        console.print(
            f"[green]✓ {agent_name} done ({format_duration(result.duration_seconds)})[/green]"
        )
        return True, result.session_id

    console.print(f"[red]✗ {agent_name} failed: {result.error_type.value}[/red]")
    return False, result.session_id


def _run_agent_with_retry(
    ctx: ReviewChainContext,
    agent_name: str,
    section_type: str,
) -> tuple[bool, str | None]:
    """Run review agent with one retry on failure."""
    success, session_id = run_single_review_agent(ctx, agent_name, section_type)
    if success:
        return True, session_id

    console.print(f"[yellow]Retrying {agent_name}...[/yellow]")
    with ctx._lock:
        ctx.session_log.append(f"Retrying {agent_name} after failure")
    return run_single_review_agent(ctx, agent_name, section_type)


# ---------------------------------------------------------------------------
# Code Review Group (4 parallel agents)
# ---------------------------------------------------------------------------


def run_parallel_code_reviews(
    ctx: ReviewChainContext,
) -> dict[str, tuple[bool, str | None]]:
    """Run 4 code review agents in parallel.

    Returns dict of {agent_name: (success, session_id)}.
    """
    results: dict[str, tuple[bool, str | None]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_run_agent_with_retry, ctx, agent_name, section_type): (
                agent_name,
                section_type,
            )
            for agent_name, section_type in CODE_REVIEW_AGENTS
        }

        for future in concurrent.futures.as_completed(futures):
            agent_name, section_type = futures[future]
            try:
                success, session_id = future.result()
                results[agent_name] = (success, session_id)
                if session_id:
                    with ctx._lock:
                        ctx.review_session_ids[agent_name] = session_id
            except Exception as e:
                logger.error("Agent %s raised exception: %s", agent_name, e)
                results[agent_name] = (False, None)

    return results


def _resume_reviewers(ctx: ReviewChainContext, iteration: int) -> None:
    """Resume each code reviewer to re-check after fixes."""
    for agent_name, section_type in CODE_REVIEW_AGENTS:
        session_id = ctx.review_session_ids.get(agent_name)
        if not session_id:
            # No session to resume — run fresh
            success, sid = run_single_review_agent(ctx, agent_name, section_type)
            if sid:
                ctx.review_session_ids[agent_name] = sid
            continue

        prompt = (
            "The implementer has fixed or declined findings. "
            "Re-review the changes and update finding statuses."
        )
        log_path = _log_path(ctx, agent_name, f"_rereview{iteration}")

        result = run_claude(
            prompt=prompt,
            working_dir=ctx.working_dir,
            log_path=log_path,
            model=ctx.settings.claude_review_model,
            resume_session=session_id,
        )

        if result.session_id:
            ctx.review_session_ids[agent_name] = result.session_id

        if result.error_type.is_success:
            console.print(f"[green]✓ {agent_name} re-review done[/green]")
        else:
            console.print(
                f"[yellow]⚠ {agent_name} re-review failed: {result.error_type.value}[/yellow]"
            )


# ---------------------------------------------------------------------------
# Phase 1: Code Review Group
# ---------------------------------------------------------------------------


def run_code_review_phase(ctx: ReviewChainContext) -> ReviewPhaseResult:
    """Run 4 parallel code review agents with iterative fix cycle."""
    max_iter = ctx.settings.code_review_max_iterations

    console.rule(f"[cyan]Code Review Group: {ctx.task_ref}[/cyan]")
    ctx.session_log.append("Code review group started")

    # Initial parallel review
    results = run_parallel_code_reviews(ctx)
    succeeded = sum(1 for s, _ in results.values() if s)

    if succeeded == 0:
        ctx.session_log.append("Code review: all agents failed")
        return ReviewPhaseResult(success=False, error="All review agents failed")

    ctx.session_log.append(f"Code review: {succeeded}/{len(results)} agents succeeded")

    open_count = 0
    for iteration in range(1, max_iter + 1):
        is_lgtm, open_count = check_lgtm(ctx.project, ctx.task_number, CODE_REVIEW_SECTION_TYPES)

        if is_lgtm:
            if iteration > 1:
                create_fixup_commit(ctx.working_dir, ctx.session_log, "code review fixes")
            ctx.session_log.append(f"Code review LGTM after {iteration} iteration(s)")
            console.print("[green]✓ Code Review Group: LGTM[/green]")
            return ReviewPhaseResult(success=True, lgtm=True)

        console.print(f"[yellow]Code review: {open_count} open findings[/yellow]")

        if iteration == max_iter:
            break

        # Fix via main session
        fix_ok = run_fix_session(ctx, CODE_REVIEW_SECTION_TYPES, iteration)
        if not fix_ok:
            ctx.session_log.append(f"Code review fix failed at iteration {iteration}")
            return ReviewPhaseResult(success=False, error="Fix session failed")

        # Re-review
        _resume_reviewers(ctx, iteration + 1)

    # Max iterations reached
    create_fixup_commit(ctx.working_dir, ctx.session_log, "code review fixes")
    ctx.session_log.append(
        f"Code review: max iterations ({max_iter}) reached, {open_count} findings remain"
    )
    console.print("[yellow]⚠ Code Review: max iterations reached[/yellow]")
    return ReviewPhaseResult(success=True, lgtm=False, findings_count=open_count)


# ---------------------------------------------------------------------------
# Phase 2: Code Simplifier
# ---------------------------------------------------------------------------


def run_simplifier_phase(ctx: ReviewChainContext) -> ReviewPhaseResult:
    """Run code simplifier (fresh session, no iterations)."""
    console.rule(f"[cyan]Code Simplifier: {ctx.task_ref}[/cyan]")
    ctx.session_log.append("Code simplifier started")

    try:
        prompt = load_prompt(
            "code-simplifier",
            task_ref=ctx.task_ref,
            project=ctx.project,
            number=str(ctx.task_number),
            base_commit=ctx.base_commit or "",
        )
    except FileNotFoundError as e:
        ctx.session_log.append(f"Code simplifier skipped: {e}")
        return ReviewPhaseResult(success=True, error=str(e))

    log_path = _log_path(ctx, "simplifier")

    result = run_claude(
        prompt=prompt,
        working_dir=ctx.working_dir,
        log_path=log_path,
        model=ctx.settings.claude_review_model,
    )

    if result.error_type.is_success:
        create_fixup_commit(ctx.working_dir, ctx.session_log, "simplifier changes")
        console.print(
            f"[green]✓ Simplifier done ({format_duration(result.duration_seconds)})[/green]"
        )
        ctx.session_log.append("Code simplifier completed")
        return ReviewPhaseResult(success=True, cost_usd=result.cost_usd)

    console.print(f"[red]✗ Simplifier failed: {result.error_type.value}[/red]")
    ctx.session_log.append(f"Code simplifier failed: {result.error_type.value}")
    return ReviewPhaseResult(success=False, error=result.error_type.value)


# ---------------------------------------------------------------------------
# Phase 3: Security Review
# ---------------------------------------------------------------------------


def run_security_review_phase(ctx: ReviewChainContext) -> ReviewPhaseResult:
    """Run security review with iterative fix cycle."""
    max_iter = ctx.settings.security_review_max_iterations
    section_types = ["security-review"]

    console.rule(f"[cyan]Security Review: {ctx.task_ref}[/cyan]")
    ctx.session_log.append("Security review started")

    # Initial review
    success, session_id = _run_agent_with_retry(ctx, "security-reviewer", "security-review")
    ctx.review_session_ids["security-reviewer"] = session_id

    if not success:
        ctx.session_log.append("Security review: agent failed")
        return ReviewPhaseResult(success=False, error="Security reviewer failed")

    open_count = 0
    for iteration in range(1, max_iter + 1):
        is_lgtm, open_count = check_lgtm(ctx.project, ctx.task_number, section_types)

        if is_lgtm:
            if iteration > 1:
                create_fixup_commit(ctx.working_dir, ctx.session_log, "security fixes")
            ctx.session_log.append(f"Security review LGTM after {iteration} iteration(s)")
            console.print("[green]✓ Security Review: LGTM[/green]")
            return ReviewPhaseResult(success=True, lgtm=True)

        console.print(f"[yellow]Security review: {open_count} open findings[/yellow]")

        if iteration == max_iter:
            break

        # Fix via main session
        fix_ok = run_fix_session(ctx, section_types, iteration)
        if not fix_ok:
            ctx.session_log.append(f"Security review fix failed at iteration {iteration}")
            return ReviewPhaseResult(success=False, error="Fix session failed")

        # Re-review (resume security session)
        sec_session_id = ctx.review_session_ids.get("security-reviewer")
        if sec_session_id:
            prompt = (
                "The implementer has fixed or declined security findings. "
                "Re-review the changes and update finding statuses."
            )
            log_path = _log_path(ctx, "security-reviewer", f"_rereview{iteration + 1}")
            result = run_claude(
                prompt=prompt,
                working_dir=ctx.working_dir,
                log_path=log_path,
                model=ctx.settings.claude_review_model,
                resume_session=sec_session_id,
            )
            if result.session_id:
                ctx.review_session_ids["security-reviewer"] = result.session_id
        else:
            run_single_review_agent(ctx, "security-reviewer", "security-review")

    # Max iterations
    create_fixup_commit(ctx.working_dir, ctx.session_log, "security fixes")
    ctx.session_log.append(f"Security review: max iterations ({max_iter}) reached")
    console.print("[yellow]⚠ Security Review: max iterations reached[/yellow]")
    return ReviewPhaseResult(success=True, lgtm=False, findings_count=open_count)


# ---------------------------------------------------------------------------
# Phase 4: Codex Review
# ---------------------------------------------------------------------------


def run_codex_review_phase(ctx: ReviewChainContext) -> ReviewPhaseResult:
    """Run codex review with iterative fix cycle (subprocess-based)."""
    console.rule(f"[cyan]Codex Review: {ctx.task_ref}[/cyan]")
    ctx.session_log.append("Codex review started")

    if not shutil.which("codex"):
        console.print("[yellow]⚠ Codex not found in PATH, skipping[/yellow]")
        ctx.session_log.append("Codex not found in PATH, skipping")
        return ReviewPhaseResult(success=True, error="Codex not found")

    try:
        initial_prompt = load_prompt(
            "codex-reviewer",
            task_ref=ctx.task_ref,
            project=ctx.project,
            number=str(ctx.task_number),
            base_commit=ctx.base_commit or "",
        )
    except FileNotFoundError:
        console.print("[yellow]⚠ Codex reviewer prompt not found[/yellow]")
        return ReviewPhaseResult(success=True, error="Prompt not found")

    max_iter = ctx.settings.codex_review_max_iterations
    model = ctx.settings.codex_review_model

    for iteration in range(1, max_iter + 1):
        console.print(f"[cyan]Codex review iteration {iteration}/{max_iter}[/cyan]")

        # Build codex command
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
            cmd = [
                "codex",
                "review",
                "-c",
                f'model="{model}"',
                "-c",
                'model_reasoning_effort="high"',
                initial_prompt,
            ]

        log_path = _log_path(ctx, "codex", f"_iter{iteration}")

        start_time = time.time()
        try:
            with open(log_path, "w") as log_file:
                proc = subprocess.Popen(
                    cmd,
                    cwd=ctx.working_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace")
                    log_file.write(line)
                proc.wait()

            duration = int(time.time() - start_time)

            if proc.returncode != 0:
                console.print(
                    f"[red]Codex review failed "
                    f"(exit {proc.returncode}, "
                    f"{format_duration(duration)})[/red]"
                )
                ctx.session_log.append(f"Codex review failed at iteration {iteration}")
                return ReviewPhaseResult(success=False, error=f"Exit code {proc.returncode}")

            console.print(f"[green]Codex review done ({format_duration(duration)})[/green]")

            # Check LGTM via Neo4j findings (consistent with other phases)
            is_lgtm, open_count = check_lgtm(ctx.project, ctx.task_number, ["codex-review"])

            if is_lgtm:
                if iteration > 1:
                    create_fixup_commit(ctx.working_dir, ctx.session_log, "codex fixes")
                ctx.session_log.append(f"Codex LGTM after {iteration} iteration(s)")
                console.print("[green]✓ Codex Review: LGTM[/green]")
                return ReviewPhaseResult(success=True, lgtm=True)

            console.print(f"[yellow]Codex review: {open_count} open finding(s)[/yellow]")

            # Fix (not on last iteration)
            if iteration < max_iter:
                fix_ok = run_fix_session(ctx, ["codex-review"], iteration)
                if not fix_ok:
                    ctx.session_log.append(f"Codex fix failed at iteration {iteration}")
                    return ReviewPhaseResult(success=False, error="Fix session failed")

        except Exception as e:
            console.print(f"[red]Codex review error: {e}[/red]")
            ctx.session_log.append(f"Codex review error: {e}")
            return ReviewPhaseResult(success=False, error=str(e))

    # Max iterations
    create_fixup_commit(ctx.working_dir, ctx.session_log, "codex fixes")
    ctx.session_log.append(f"Codex review: max iterations ({max_iter}) reached")
    console.print("[yellow]⚠ Codex Review: max iterations reached[/yellow]")
    return ReviewPhaseResult(success=True, lgtm=False)


# ---------------------------------------------------------------------------
# Phase 5: Finalization
# ---------------------------------------------------------------------------


def run_finalization_phase(ctx: ReviewChainContext) -> ReviewPhaseResult:
    """Resume main session for finalization (tests, linters, task update)."""
    console.rule(f"[cyan]Finalization: {ctx.task_ref}[/cyan]")
    ctx.session_log.append("Finalization started")

    try:
        prompt = load_prompt(
            "finalization",
            task_ref=ctx.task_ref,
            project=ctx.project,
            number=str(ctx.task_number),
        )
    except FileNotFoundError as e:
        ctx.session_log.append(f"Finalization prompt not found: {e}")
        return ReviewPhaseResult(success=False, error=str(e))

    log_path = _log_path(ctx, "finalization")

    result = run_claude(
        prompt=prompt,
        working_dir=ctx.working_dir,
        log_path=log_path,
        resume_session=ctx.main_session_id,
    )

    if result.error_type.is_success:
        console.print(
            f"[green]✓ Finalization done ({format_duration(result.duration_seconds)})[/green]"
        )
        ctx.session_log.append("Finalization completed")
        return ReviewPhaseResult(success=True, cost_usd=result.cost_usd)

    console.print(f"[red]✗ Finalization failed: {result.error_type.value}[/red]")
    ctx.session_log.append(f"Finalization failed: {result.error_type.value}")
    return ReviewPhaseResult(success=False, error=result.error_type.value)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_review_chain(
    task_ref: str,
    working_dir: Path,
    log_dir: Path,
    settings: Settings,
    session_log: SessionLog,
    main_session_id: str | None = None,
    notifier: Notifier | None = None,
    base_commit: str | None = None,
) -> bool:
    """Run full review chain after main implementation.

    Phases: Code Review → Simplifier → Security → Codex → Finalization

    Returns True if chain completed, False on fatal error.
    """
    project, task_number = _parse_task_ref(task_ref)

    if notifier is None:
        notifier = Notifier()

    review_log_dir = log_dir / "reviews"
    review_log_dir.mkdir(parents=True, exist_ok=True)

    ctx = ReviewChainContext(
        task_ref=task_ref,
        project=project,
        task_number=task_number,
        working_dir=working_dir,
        log_dir=review_log_dir,
        settings=settings,
        session_log=session_log,
        notifier=notifier,
        main_session_id=main_session_id,
        base_commit=base_commit,
    )

    console.rule(f"[bold blue]Review Chain: {task_ref}[/bold blue]")
    session_log.append(f"Review chain started: {task_ref}")

    log_dir_str = str(ctx.log_dir)

    # Phase 1: Code Review Group
    code_review = run_code_review_phase(ctx)
    if not code_review.success:
        notifier.review_failed(
            task_ref, "Code Review Group", code_review.error or "Unknown", log_dir_str
        )

    # Phase 2: Code Simplifier
    simplifier = run_simplifier_phase(ctx)

    # Phase 3: Security Review
    security = run_security_review_phase(ctx)
    if not security.success:
        notifier.review_failed(
            task_ref, "Security Review", security.error or "Unknown", log_dir_str
        )

    # Phase 4: Codex Review
    codex = run_codex_review_phase(ctx)
    if not codex.success:
        notifier.review_failed(task_ref, "Codex Review", codex.error or "Unknown", log_dir_str)

    # Phase 5: Finalization
    finalization = run_finalization_phase(ctx)

    session_log.append(f"Review chain completed: {task_ref}")
    console.rule(f"[bold blue]Review Chain Complete: {task_ref}[/bold blue]")

    # Summary
    phases = [
        ("Code Review", code_review),
        ("Simplifier", simplifier),
        ("Security", security),
        ("Codex", codex),
        ("Finalization", finalization),
    ]

    for name, result in phases:
        if result.lgtm and result.success:
            status = "[green]✓ LGTM[/green]"
        elif not result.success:
            status = f"[red]✗ FAIL ({result.error})[/red]"
        else:
            status = "[yellow]⚠ Issues remain[/yellow]"
        console.print(f"  {name}: {status}")

    return finalization.success
