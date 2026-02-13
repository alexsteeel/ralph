"""Health check command."""

from rich.console import Console

from ..health import check_health

console = Console()


def run_health(verbose: bool = False) -> int:
    """Run health check and return exit code."""
    result = check_health(verbose=verbose)

    if verbose or not result.is_healthy:
        if result.is_healthy:
            console.print(f"[green]✓ {result.message}[/green]")
        else:
            console.print(f"[red]✗ {result.error_type.value}: {result.message}[/red]")

    return result.exit_code
