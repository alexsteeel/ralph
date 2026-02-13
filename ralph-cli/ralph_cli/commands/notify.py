"""Notify command - send Telegram notifications."""

from rich.console import Console

from ..notify import Notifier

console = Console()


def run_notify(message: str, test: bool = False) -> int:
    """Send notification to Telegram.

    Args:
        message: Message to send
        test: If True, send a test message instead

    Returns:
        0 on success, 1 on failure
    """
    notifier = Notifier()

    if not notifier.is_configured:
        console.print("[red]Error: Telegram not configured[/red]")
        console.print("[dim]Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in ~/.claude/.env[/dim]")
        return 1

    if test:
        message = "🧪 *Test notification from Ralph CLI*\n\nTelegram integration is working!"

    success = notifier._send(message)

    if success:
        console.print("[green]✓ Notification sent[/green]")
        return 0
    else:
        console.print("[red]✗ Failed to send notification[/red]")
        return 1
