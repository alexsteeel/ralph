"""Connect command for worktree management."""

import subprocess
from pathlib import Path

import click
import inquirer

from .utils import (
    get_running_container_name,
    get_task_description,
    list_worktrees,
)


@click.command()
@click.argument("name", required=False)
@click.pass_context
def connect(ctx: click.Context, name: str | None) -> None:
    """Connect to an existing worktree.

    Can specify worktree by name/branch or select interactively.

    \b
    Examples:
        ai-sbx worktree connect                  # Interactive selection
        ai-sbx worktree connect test-feature     # Connect to specific worktree
    """
    from rich.console import Console

    console: Console = ctx.obj["console"]

    # Get list of worktrees (excluding main repository)
    worktrees = list_worktrees(exclude_current=True)

    if not worktrees:
        console.print("[yellow]No worktrees found[/yellow]")
        console.print("[dim]Use 'ai-sbx worktree create \"task description\"' to create one[/dim]")
        return

    selected = None

    # If name provided, try to find matching worktree
    if name:
        for w in worktrees:
            path = Path(w["path"])
            branch = w.get("branch", "")
            # Match by path name or branch name
            if name in path.name or name == branch:
                selected = w
                break

        if not selected:
            console.print(f"[red]No worktree found matching: {name}[/red]")
            console.print("\nAvailable worktrees:")
            for w in worktrees:
                path = Path(w["path"])
                branch = w.get("branch", "")
                console.print(f"  • {path.name} ({branch})")
            return
    else:
        # Interactive selection
        # Create choice list with task descriptions
        choices = []
        for w in worktrees:
            path = Path(w["path"])
            label = path.name

            if w.get("branch"):
                label += f" ({w['branch']})"

            # Try to get task description
            desc = get_task_description(path)
            if desc:
                label += f" - {desc}"

            choices.append((label, w))

        questions = [
            inquirer.List(
                "worktree",
                message="Select worktree to connect to",
                choices=choices,
            )
        ]

        answers = inquirer.prompt(questions)
        if not answers:
            return

        selected = answers["worktree"]
    path = Path(selected["path"])

    if not path.exists():
        console.print("[red]Worktree path does not exist[/red]")
        console.print(f"Path: {path}")
        console.print(
            "You may need to remove this worktree with: [cyan]ai-sbx worktree remove[/cyan]"
        )
        return

    # Check container status
    container_base_name = f"{path.name}-devcontainer"
    actual_container_name = get_running_container_name(container_base_name)

    if actual_container_name:
        # Container is running - offer to connect
        console.print(f"[green]Container '{container_base_name}' is running[/green]")

        connect_choices = [
            ("Open shell in container", "shell"),
            ("Just change directory", "cd"),
            ("Cancel", "cancel"),
        ]

        questions = [
            inquirer.List(
                "action",
                message="What would you like to do?",
                choices=connect_choices,
            )
        ]

        answers = inquirer.prompt(questions)
        if not answers or answers["action"] == "cancel":
            return

        if answers["action"] == "shell":
            # Connect to container using actual name
            console.print(f"Connecting to container: [cyan]{actual_container_name}[/cyan]")
            console.print("[dim]Type 'exit' to disconnect[/dim]\n")

            # Use subprocess for safer execution with shell fallback
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-it",
                    actual_container_name,
                    "sh",
                    "-lc",
                    "if [ -x /bin/zsh ]; then exec /bin/zsh; "
                    "elif [ -x /bin/bash ]; then exec /bin/bash; else exec /bin/sh; fi",
                ]
            )
        elif answers["action"] == "cd":
            # Just show cd command
            console.print("\nTo navigate to worktree, run:")
            console.print(f"[cyan]cd {path}[/cyan]")
    else:
        # Container not running
        console.print(f"[yellow]Container '{container_base_name}' is not running[/yellow]")
        console.print("\nTo start the container:")
        console.print(f"1. Navigate to worktree: [cyan]cd {path}[/cyan]")
        console.print("2. Start the container: [cyan]devcontainer up --workspace-folder .[/cyan]")
