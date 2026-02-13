"""
Common utilities for Claude Code hooks.

Provides unified logging to ~/.claude/logs/hooks/
"""

from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".claude" / "logs" / "hooks"


def get_logger(hook_name: str):
    """
    Get a logger function for a specific hook.

    Usage:
        log = get_logger("my_hook")
        log("EVENT", "message")
        log("ERROR", "something failed")

    Writes to: ~/.claude/logs/hooks/{hook_name}.log
    Format: [YYYY-MM-DD HH:MM:SS] EVENT: message
    """
    log_file = LOG_DIR / f"{hook_name}.log"

    def log(event: str, message: str = ""):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {event}: {message}" if message else f"[{timestamp}] {event}"
        with log_file.open("a") as f:
            f.write(line + "\n")

    return log
