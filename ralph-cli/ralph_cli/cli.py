"""CLI definition with typer."""

from pathlib import Path
from typing import Annotated

import typer

from .commands.logs import LogType, complete_log_files


def validate_project_name(value: str) -> str:
    """Validate project name is not numeric-only."""
    if value.isdigit():
        raise typer.BadParameter(
            f"Project name '{value}' cannot be numeric-only. "
            f"Did you forget the project name? Example: ralph plan myproject {value}"
        )
    return value


def validate_task_numbers(values: list[str]) -> list[str]:
    """Validate task numbers/ranges contain only digits and dashes."""
    for v in values:
        # Allow ranges like "1-4" and single numbers like "6"
        clean = v.replace("-", "")
        if not clean.isdigit():
            raise typer.BadParameter(
                f"Task '{v}' is invalid. Tasks must be numbers or ranges (e.g., 1 2-5 8)."
            )
    return values


app = typer.Typer(
    help="Ralph - Autonomous task execution CLI",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Logs sub-application
logs_app = typer.Typer(
    help="View and manage log files",
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(logs_app, name="logs")


@app.command()
def interview(
    project: Annotated[str, typer.Argument(help="Project name", callback=validate_project_name)],
    tasks: Annotated[
        list[str],
        typer.Argument(
            help="Task numbers or ranges (e.g., 1-4 6 8-10)", callback=validate_task_numbers
        ),
    ],
    working_dir: Path | None = typer.Option(None, "-w", "--working-dir", help="Working directory"),
):
    """Deep interview to create detailed task specifications."""
    from .commands.interview import run_interview

    raise typer.Exit(run_interview(project, tasks, working_dir))


@app.command()
def plan(
    project: Annotated[str, typer.Argument(help="Project name", callback=validate_project_name)],
    tasks: Annotated[
        list[str],
        typer.Argument(
            help="Task numbers or ranges (e.g., 1-4 6 8-10)", callback=validate_task_numbers
        ),
    ],
    working_dir: Path | None = typer.Option(None, "-w", "--working-dir", help="Working directory"),
):
    """Interactive task planning with human feedback."""
    from .commands.plan import run_plan

    raise typer.Exit(run_plan(project, tasks, working_dir))


@app.command()
def implement(
    project: Annotated[str, typer.Argument(help="Project name", callback=validate_project_name)],
    tasks: Annotated[
        list[str],
        typer.Argument(
            help="Task numbers or ranges (e.g., 1-4 6 8-10)", callback=validate_task_numbers
        ),
    ],
    working_dir: Path | None = typer.Option(None, "-w", "--working-dir", help="Working directory"),
    prompt: str | None = typer.Option(
        None, "--prompt", help="Additional prompt appended to each task"
    ),
):
    """Autonomous implementation with recovery and notifications."""
    from .commands.implement import run_implement

    raise typer.Exit(run_implement(project, tasks, working_dir, extra_prompt=prompt))


@app.command()
def review(
    task_ref: str = typer.Argument(..., help="Task reference (e.g., project#1)"),
):
    """Run code reviews in isolated contexts."""
    from .commands.review import run_review

    raise typer.Exit(run_review(task_ref))


@app.command()
def health(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed output"),
):
    """Check API health status."""
    from .commands.health import run_health

    raise typer.Exit(run_health(verbose))


@app.command()
def notify(
    message: str | None = typer.Argument(None, help="Message to send"),
    test: bool = typer.Option(False, "-t", "--test", help="Send test message"),
):
    """Send notification to Telegram."""
    from .commands.notify import run_notify

    if not message and not test:
        raise typer.BadParameter("Provide a message or use --test")

    raise typer.Exit(run_notify(message or "", test))


# ============================================================================
# Logs subcommands
# ============================================================================


@logs_app.callback(invoke_without_command=True)
def logs_list(
    ctx: typer.Context,
    log_type: Annotated[
        LogType | None,
        typer.Option(
            "-t",
            "--type",
            help="Filter by log type",
        ),
    ] = None,
    task: Annotated[
        str | None,
        typer.Option(
            "--task",
            help="Filter by task reference (e.g., project#1)",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "-n",
            "--limit",
            help="Maximum number of logs to show",
        ),
    ] = 20,
):
    """List recent log files."""
    # Only run if no subcommand was invoked
    if ctx.invoked_subcommand is None:
        from .commands.logs import list_logs

        raise typer.Exit(list_logs(log_type, task, limit))


@logs_app.command("view")
def logs_view(
    path: Annotated[
        str,
        typer.Argument(
            help="Log file path or name",
            autocompletion=complete_log_files,
        ),
    ],
    lines: Annotated[
        int | None,
        typer.Option(
            "-n",
            "--lines",
            help="Number of lines to show",
        ),
    ] = None,
    head: Annotated[
        bool,
        typer.Option(
            "--head",
            help="Show first N lines instead of last",
        ),
    ] = False,
    pager: Annotated[
        bool,
        typer.Option(
            "--pager",
            help="Force use of pager (less)",
        ),
    ] = False,
    no_pager: Annotated[
        bool,
        typer.Option(
            "--no-pager",
            help="Disable pager, output directly",
        ),
    ] = False,
    vim: Annotated[
        bool,
        typer.Option(
            "--vim",
            "-v",
            help="Open in vim",
        ),
    ] = False,
    editor: Annotated[
        bool,
        typer.Option(
            "--editor",
            "-e",
            help="Open in $EDITOR",
        ),
    ] = False,
):
    """View log file contents with syntax highlighting.

    By default, uses pager for files > 50KB.
    Use --vim or --editor to open in external editor.
    """
    from .commands.logs import view_log

    # Determine pager mode: None=auto, True=force, False=disable
    use_pager: bool | None = None
    if pager:
        use_pager = True
    elif no_pager:
        use_pager = False

    raise typer.Exit(view_log(path, lines, head, use_pager, vim, editor))


@logs_app.command("tail")
def logs_tail(
    path: Annotated[
        str,
        typer.Argument(
            help="Log file path or name",
            autocompletion=complete_log_files,
        ),
    ],
    lines: Annotated[
        int,
        typer.Option(
            "-n",
            "--lines",
            help="Initial number of lines to show",
        ),
    ] = 50,
):
    """Tail log file in real-time (like tail -f)."""
    from .commands.logs import tail_log

    raise typer.Exit(tail_log(path, lines))


@logs_app.command("clean")
def logs_clean(
    log_type: Annotated[
        LogType | None,
        typer.Option(
            "-t",
            "--type",
            help="Filter by log type",
        ),
    ] = None,
    days: Annotated[
        int,
        typer.Option(
            "--days",
            help="Delete logs older than this many days",
        ),
    ] = 30,
    no_dry_run: Annotated[
        bool,
        typer.Option(
            "--no-dry-run",
            help="Actually delete files (default is dry-run)",
        ),
    ] = False,
):
    """Clean old log files."""
    from .commands.logs import clean_logs

    raise typer.Exit(clean_logs(log_type, days, dry_run=not no_dry_run))


def main():
    """Entry point."""
    app()
