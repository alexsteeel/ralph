"""Claude process execution."""

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .errors import ErrorType, classify_from_text
from .logging import TaskLog, format_duration
from .monitor import StreamMonitor

# Env vars that prevent nested Claude Code sessions
_CLAUDE_SESSION_VARS = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}


def _clean_env() -> dict[str, str]:
    """Return env dict without Claude session vars to allow nested launches."""
    return {k: v for k, v in os.environ.items() if k not in _CLAUDE_SESSION_VARS}


@dataclass
class TaskResult:
    """Result of task execution."""

    task_ref: str
    error_type: ErrorType
    exit_code: int
    duration_seconds: int
    log_path: Path
    session_id: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def expand_task_ranges(args: list[str]) -> list[int]:
    """Expand task range notation to list of numbers.

    Examples:
        ['1-4', '6', '8-10'] -> [1, 2, 3, 4, 6, 8, 9, 10]
        ['1', '2', '3'] -> [1, 2, 3]
        ['1-3'] -> [1, 2, 3]
    """
    result = []
    for arg in args:
        if "-" in arg:
            try:
                start, end = arg.split("-", 1)
                result.extend(range(int(start), int(end) + 1))
            except ValueError:
                # Not a valid range, try as single number
                try:
                    result.append(int(arg))
                except ValueError:
                    pass
        else:
            try:
                result.append(int(arg))
            except ValueError:
                pass
    return result


def build_prompt(
    skill: str,
    task_ref: str,
    recovery_note: str | None = None,
    extra_prompt: str | None = None,
) -> str:
    """Build prompt for Claude execution.

    Args:
        skill: Skill name (e.g., 'ralph-implement-python-task')
        task_ref: Task reference (e.g., 'myproject#1')
        recovery_note: Optional note about recovery context
        extra_prompt: Optional additional instructions appended after skill invocation
    """
    prompt = f"/{skill} {task_ref}"
    if recovery_note:
        prompt = f"{recovery_note}\n\n{prompt}"
    if extra_prompt:
        prompt = f"{prompt}\n\n{extra_prompt}"
    return prompt


def run_claude(
    prompt: str,
    working_dir: Path,
    log_path: Path,
    model: str = "opus",
    resume_session: str | None = None,
    output: TextIO = sys.stdout,
) -> TaskResult:
    """Execute Claude with given prompt.

    Args:
        prompt: The prompt to send
        working_dir: Working directory for Claude
        log_path: Path to write log file
        model: Model to use (opus, sonnet, haiku)
        resume_session: Session ID to resume
        output: Stream for formatted output

    Returns:
        TaskResult with execution details
    """
    # Build command
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    if resume_session:
        cmd.extend(["--resume", resume_session])

    # Extract task_ref from prompt for logging
    task_ref_match = re.search(r"(\w+#\d+)", prompt)
    task_ref = task_ref_match.group(1) if task_ref_match else "unknown"

    start_time = time.time()

    # Raw JSON log path (same name with .json extension)
    raw_json_path = log_path.with_suffix(".json")

    with TaskLog(log_path) as task_log, open(raw_json_path, "w") as raw_json_file:
        task_log.write_header(task_ref)

        # Create monitor with both output and log file
        monitor = StreamMonitor(
            output=output,
            log_file=task_log._file,
            raw_json_file=raw_json_file,
        )

        # Run process
        process = subprocess.Popen(
            cmd,
            cwd=working_dir,
            env=_clean_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Process stream
        try:
            if process.stdout:
                result = monitor.process_stream(process.stdout)
            else:
                result = None
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise

        try:
            exit_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait()
        duration = int(time.time() - start_time)

        # Determine error type
        if result:
            error_type = result.error_type
            session_id = result.session_id
        else:
            # Fallback to log-based classification
            error_type = classify_from_text(log_path.read_text())
            session_id = None

        # Write footer
        task_log.write_footer(
            format_duration(duration),
            error_type.value,
        )

        monitor.print_summary()

    # Extract stats from monitor result
    cost_usd = result.stats.cost_usd if result else 0.0
    input_tokens = result.stats.input_tokens if result else 0
    output_tokens = result.stats.output_tokens if result else 0

    return TaskResult(
        task_ref=task_ref,
        error_type=error_type,
        exit_code=exit_code,
        duration_seconds=duration,
        log_path=log_path,
        session_id=session_id,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
