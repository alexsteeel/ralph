"""
tm: Simple CLI for markdown-based task management.

Commands:
    tm p, tm project         Project commands
    tm p list, tm p ls, tm p List all projects
    tm p add <name>          Add a new project

    tm t, tm task            Task commands
    tm t list, tm t ls, tm t List all tasks (tree view)
    tm t list <project>      List tasks in specific project
    tm t add [project]       Add a new task
    tm t show <project> <n>  Show task details
    tm t open <project> [n]  Open task in editor

    tm completion SHELL      Generate shell completion
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from .core import (
    Task,
    ensure_base_dir,
    find_task_file,
    get_next_task_number,
    get_project_dir,
    list_projects,
    read_task,
    write_task,
)
from .core import (
    list_tasks as core_list_tasks,
)

STATUS_SYMBOLS = {"todo": "[ ]", "work": "[*]", "done": "[x]"}


def open_in_editor(file_path: Path, editor: str | None = None) -> int:
    """Open a file in the configured editor."""
    if editor:
        editor_cmd = editor
    else:
        editor_cmd = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))

    try:
        subprocess.run([editor_cmd, str(file_path)], check=True)
        return 0
    except FileNotFoundError:
        click.echo(f"Editor '{editor_cmd}' not found.", err=True)
        click.echo("Set EDITOR environment variable or use --editor option.", err=True)
        return 1
    except subprocess.CalledProcessError as e:
        return e.returncode


def select_project(prompt_text: str = "Select project") -> str | None:
    """Show project list and prompt for selection."""
    projects = list_projects()
    if not projects:
        click.echo("No projects found. Create one with: tm p add <name>", err=True)
        return None

    click.echo("Available projects:")
    for i, proj in enumerate(projects, 1):
        click.echo(f"  {i}. {proj}")
    click.echo()

    choice = click.prompt(prompt_text, type=int)
    if 1 <= choice <= len(projects):
        return projects[choice - 1]
    else:
        click.echo("Invalid selection.", err=True)
        return None


# ============================================================================
# Main CLI group
# ============================================================================

class AliasedGroup(click.Group):
    """Click group that shows aliases together with commands."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aliases: dict[str, str] = {}  # alias -> command name

    def add_alias(self, alias: str, cmd_name: str):
        """Register an alias for a command."""
        self._aliases[alias] = cmd_name

    def get_command(self, ctx, cmd_name):
        # Resolve alias to actual command
        if cmd_name in self._aliases:
            cmd_name = self._aliases[cmd_name]
        return super().get_command(ctx, cmd_name)

    def list_commands(self, ctx):
        # Only return actual commands, not aliases
        return [cmd for cmd in super().list_commands(ctx) if cmd not in self._aliases]

    def format_commands(self, ctx, formatter):
        """Format commands with their aliases."""
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue

            # Find aliases for this command
            aliases = sorted([a for a, c in self._aliases.items() if c == subcommand])
            if aliases:
                name = f"{subcommand}, {', '.join(aliases)}"
            else:
                name = subcommand

            help_text = cmd.get_short_help_str(limit=formatter.width)
            commands.append((name, help_text))

        if commands:
            with formatter.section("Commands"):
                formatter.write_dl(commands)


@click.group(cls=AliasedGroup)
@click.version_option(version="0.1.0", prog_name="tm")
def cli():
    """Task management CLI."""
    pass


# ============================================================================
# Project commands: tm project / tm p
# ============================================================================

@cli.group("project", cls=AliasedGroup, invoke_without_command=True)
@click.pass_context
def project_group(ctx):
    """Project management commands."""
    if ctx.invoked_subcommand is None:
        # Default: list projects
        ctx.invoke(project_list)


@project_group.command("list")
def project_list():
    """List all projects."""
    projects = list_projects()

    if not projects:
        click.echo("No projects found.")
        return

    for proj in projects:
        tasks = core_list_tasks(proj)
        task_count = len(tasks)
        if task_count > 0:
            work = sum(1 for t in tasks if t.status == "work")
            todo = sum(1 for t in tasks if t.status == "todo")
            done = sum(1 for t in tasks if t.status == "done")
            click.echo(f"{proj} ({task_count}: {work}w/{todo}t/{done}d)")
        else:
            click.echo(f"{proj} (empty)")


@project_group.command("add")
@click.argument("name")
def project_add(name: str):
    """Add a new project."""
    ensure_base_dir()
    project_dir = get_project_dir(name)

    if project_dir.exists():
        click.echo(f"Project '{name}' already exists.", err=True)
        sys.exit(1)

    get_project_dir(name, create=True)
    click.echo(f"Created project: {name}")


# Aliases for project subcommands
project_group.add_alias("ls", "list")


# ============================================================================
# Task commands: tm task / tm t
# ============================================================================

@cli.group("task", cls=AliasedGroup, invoke_without_command=True)
@click.pass_context
def task_group(ctx):
    """Task management commands."""
    if ctx.invoked_subcommand is None:
        # Default: list all tasks (tree view)
        ctx.invoke(task_list)


@task_group.command("list")
@click.argument("project", required=False)
@click.argument("task_number", type=int, required=False)
def task_list(project: str | None, task_number: int | None):
    """List tasks. Without project: show tree of all. With project: list tasks."""
    # No project - show tree of all projects and tasks
    if project is None:
        projects = list_projects()
        if not projects:
            click.echo("No projects found.")
            return

        for proj in projects:
            tasks = core_list_tasks(proj)
            task_count = len(tasks)
            work_count = sum(1 for t in tasks if t.status == "work")
            todo_count = sum(1 for t in tasks if t.status == "todo")
            done_count = sum(1 for t in tasks if t.status == "done")

            click.echo(f"{proj}/ ({task_count}: {work_count}w/{todo_count}t/{done_count}d)")
            for task in tasks:
                symbol = STATUS_SYMBOLS.get(task.status, "[ ]")
                click.echo(f"  {symbol} #{task.number}: {task.description}")
        return

    # Project specified
    project_dir = get_project_dir(project)
    if not project_dir.exists():
        click.echo(f"Project '{project}' does not exist.", err=True)
        sys.exit(1)

    tasks = core_list_tasks(project)

    if not tasks:
        click.echo(f"No tasks in '{project}'.")
        return

    # If task number specified, show details
    if task_number is not None:
        task = read_task(project, task_number)
        if task is None:
            click.echo(f"Task #{task_number} not found.", err=True)
            sys.exit(1)
        _print_task_details(task)
        return

    # List tasks in project
    for task in tasks:
        symbol = STATUS_SYMBOLS.get(task.status, "[ ]")
        click.echo(f"{symbol} #{task.number}: {task.description}")


@task_group.command("add")
@click.argument("project", required=False)
@click.option("-d", "--description", help="Task description")
@click.option("-e", "--edit", is_flag=True, help="Open in editor after creating")
@click.option("--editor", help="Editor to use (default: $EDITOR)")
def task_add(project: str | None, description: str | None, edit: bool, editor: str | None):
    """Add a new task. If project not specified, prompts for selection."""
    ensure_base_dir()

    # If no project specified, show list and ask
    if project is None:
        project = select_project("Project number")
        if project is None:
            sys.exit(1)

    # Check if project exists, create if not
    project_dir = get_project_dir(project)
    if not project_dir.exists():
        if click.confirm(f"Project '{project}' doesn't exist. Create it?", default=True):
            get_project_dir(project, create=True)
        else:
            sys.exit(1)

    if not description:
        description = click.prompt("Description")

    if not description:
        click.echo("Description cannot be empty.", err=True)
        sys.exit(1)

    task_number = get_next_task_number(project)
    task = Task(
        number=task_number,
        description=description,
    )

    task_path = write_task(project, task)

    click.echo(f"Created #{task_number}: {description}")
    click.echo(f"File: {task_path}")

    if edit:
        sys.exit(open_in_editor(task_path, editor))


@task_group.command("show")
@click.argument("project")
@click.argument("task_number", type=int)
def task_show(project: str, task_number: int):
    """Show task details."""
    project_dir = get_project_dir(project)
    if not project_dir.exists():
        click.echo(f"Project '{project}' does not exist.", err=True)
        sys.exit(1)

    task = read_task(project, task_number)
    if task is None:
        click.echo(f"Task #{task_number} not found.", err=True)
        sys.exit(1)

    _print_task_details(task)


@task_group.command("open")
@click.argument("project")
@click.argument("task_number", type=int, required=False)
@click.option("--editor", help="Editor to use (default: $EDITOR)")
def task_open(project: str, task_number: int | None, editor: str | None):
    """Open task file in editor."""
    project_dir = get_project_dir(project)

    if not project_dir.exists():
        click.echo(f"Project '{project}' does not exist.", err=True)
        sys.exit(1)

    if task_number is None:
        tasks = core_list_tasks(project)
        if not tasks:
            click.echo(f"No tasks in '{project}'.")
            sys.exit(1)

        click.echo("Tasks:")
        for task in tasks:
            click.echo(f"  #{task.number}: {task.description}")
        click.echo()
        task_number = click.prompt("Task number", type=int)

    task_file = find_task_file(project, task_number)
    if task_file is None:
        click.echo(f"Task #{task_number} not found.", err=True)
        sys.exit(1)

    sys.exit(open_in_editor(task_file, editor))


def _print_task_details(task: Task):
    """Print full task details."""
    click.echo(f"# Task {task.number}: {task.description}")
    click.echo(f"status: {task.status}")
    if task.module:
        click.echo(f"module: {task.module}")
    if task.branch:
        click.echo(f"branch: {task.branch}")
    if task.started:
        click.echo(f"started: {task.started}")
    if task.completed:
        click.echo(f"completed: {task.completed}")
    if task.body.strip():
        click.echo()
        click.echo("## Description")
        click.echo(task.body.rstrip())
    if task.plan.strip():
        click.echo()
        click.echo("## Plan")
        click.echo(task.plan.rstrip())


# Aliases for task subcommands
task_group.add_alias("ls", "list")


# ============================================================================
# Top-level aliases: tm p -> tm project, tm t -> tm task
# ============================================================================

cli.add_alias("p", "project")
cli.add_alias("t", "task")


# ============================================================================
# Shell completion
# ============================================================================

@cli.command("completion")
@click.argument("shell", type=click.Choice(["zsh", "bash"]))
@click.option("--install", is_flag=True, help="Install completion to shell config")
def cmd_completion(shell: str, install: bool):
    """Generate shell completion script."""
    if install:
        if shell == "zsh":
            zfunc_dir = Path.home() / ".zfunc"
            zfunc_dir.mkdir(exist_ok=True)
            completion_file = zfunc_dir / "_tm"
            completion_file.write_text(ZSH_COMPLETION, encoding="utf-8")
            click.echo(f"Installed completion to {completion_file}")
            click.echo("\nAdd this to your ~/.zshrc (if not already present):")
            click.echo('  fpath+=~/.zfunc; autoload -Uz compinit; compinit')
            click.echo("\nThen restart your shell: exec zsh")
        elif shell == "bash":
            bash_comp_dir = Path.home() / ".local" / "share" / "bash-completion" / "completions"
            bash_comp_dir.mkdir(parents=True, exist_ok=True)
            completion_file = bash_comp_dir / "tm"
            completion_file.write_text(BASH_COMPLETION, encoding="utf-8")
            click.echo(f"Installed completion to {completion_file}")
            click.echo("\nRestart your shell to enable completion.")
    else:
        if shell == "zsh":
            click.echo(ZSH_COMPLETION)
        elif shell == "bash":
            click.echo(BASH_COMPLETION)


ZSH_COMPLETION = r'''#compdef tm

_tm() {
    local curcontext="$curcontext" state line
    typeset -A opt_args
    local base_dir="$HOME/.md-task-mcp"

    _arguments -C \
        '1: :->command' \
        '2: :->subcommand' \
        '*: :->args'

    case $state in
        command)
            local commands=(
                'p:Project commands'
                'project:Project commands'
                't:Task commands'
                'task:Task commands'
                'completion:Generate shell completion'
            )
            _describe 'command' commands
            ;;
        subcommand)
            case $line[1] in
                p|project)
                    local subcmds=(
                        'list:List all projects'
                        'ls:List all projects'
                        'add:Add a new project'
                    )
                    _describe 'subcommand' subcmds
                    ;;
                t|task)
                    local subcmds=(
                        'list:List tasks'
                        'ls:List tasks'
                        'add:Add a new task'
                        'show:Show task details'
                        'open:Open task in editor'
                    )
                    _describe 'subcommand' subcmds
                    ;;
            esac
            ;;
        args)
            case $line[1] in
                p|project)
                    case $line[2] in
                        add)
                            # No completion for new project name
                            ;;
                    esac
                    ;;
                t|task)
                    case $line[2] in
                        list|ls|add|show|open)
                            if [[ $CURRENT -eq 4 ]]; then
                                local projects=()
                                [[ -d "$base_dir" ]] && projects=($(ls -1 "$base_dir" 2>/dev/null))
                                _describe 'project' projects
                            elif [[ $CURRENT -eq 5 ]]; then
                                local project=$line[3]
                                local tasks_dir="$base_dir/$project/tasks"
                                local tasks=()
                                [[ -d "$tasks_dir" ]] && tasks=($(ls -1 "$tasks_dir" 2>/dev/null | grep -oP '^\d+'))
                                _describe 'task' tasks
                            fi
                            ;;
                    esac
                    ;;
            esac
            ;;
    esac
}

_tm "$@"
'''

BASH_COMPLETION = r'''_tm() {
    local cur prev words cword
    _init_completion || return

    local base_dir="$HOME/.md-task-mcp"

    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "p project t task completion" -- "$cur"))
        return
    fi

    local cmd="${words[1]}"

    case $cmd in
        p|project)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "list ls add" -- "$cur"))
            fi
            ;;
        t|task)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "list ls add show open" -- "$cur"))
            elif [[ $cword -eq 3 ]]; then
                local subcmd="${words[2]}"
                case $subcmd in
                    list|ls|add|show|open)
                        local projects=""
                        [[ -d "$base_dir" ]] && projects=$(ls -1 "$base_dir" 2>/dev/null)
                        COMPREPLY=($(compgen -W "$projects" -- "$cur"))
                        ;;
                esac
            elif [[ $cword -eq 4 ]]; then
                local subcmd="${words[2]}"
                case $subcmd in
                    show|open|list|ls)
                        local project="${words[3]}"
                        local tasks_dir="$base_dir/$project/tasks"
                        local tasks=""
                        [[ -d "$tasks_dir" ]] && tasks=$(ls -1 "$tasks_dir" 2>/dev/null | grep -oP '^\d+')
                        COMPREPLY=($(compgen -W "$tasks" -- "$cur"))
                        ;;
                esac
            fi
            ;;
        completion)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "zsh bash" -- "$cur"))
            fi
            ;;
    esac
}

complete -F _tm tm
'''


def main() -> int:
    """Main entry point."""
    cli()
    return 0


if __name__ == "__main__":
    sys.exit(main())
