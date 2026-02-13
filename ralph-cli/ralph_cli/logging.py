"""Logging utilities using rich."""

from datetime import datetime
from pathlib import Path
from typing import TextIO

from rich.console import Console

# Global console instance
console = Console()

# ANSI color codes for stream output (not using rich markup)
NC = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
DIM = "\033[90m"


def timestamp() -> str:
    """Return formatted timestamp."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def timestamp_short() -> str:
    """Return short timestamp for inline use."""
    return datetime.now().strftime("%H:%M:%S")


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class SessionLog:
    """Session log file writer."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write_header(self, title: str, **fields):
        """Write session header."""
        with open(self.log_path, "w") as f:
            f.write(f"{'═' * 60}\n")
            f.write(f"{title}\n")
            f.write(f"{'═' * 60}\n\n")
            f.write(f"Started: {timestamp()}\n")
            for key, value in fields.items():
                f.write(f"{key}: {value}\n")
            f.write(f"\n{'─' * 60}\n")
            f.write("EXECUTION LOG\n")
            f.write(f"{'─' * 60}\n")

    def append(self, message: str):
        """Append line to log."""
        with open(self.log_path, "a") as f:
            f.write(f"[{timestamp()}] {message}\n")

    def write_summary(self, **sections):
        """Write session summary."""
        with open(self.log_path, "a") as f:
            f.write(f"\n{'─' * 60}\n")
            f.write("SESSION SUMMARY\n")
            f.write(f"{'─' * 60}\n\n")
            f.write(f"Finished: {timestamp()}\n\n")
            for section, lines in sections.items():
                f.write(f"{section}:\n")
                for line in lines:
                    f.write(f"  {line}\n")
            f.write(f"\n{'═' * 60}\n")


class TaskLog:
    """Task log file writer."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO | None = None

    def __enter__(self):
        self._file = open(self.log_path, "w")
        return self

    def __exit__(self, *args):
        if self._file:
            self._file.close()
            self._file = None

    def write_header(self, task_ref: str):
        """Write task header."""
        if self._file:
            self._file.write(f"{'═' * 60}\n")
            self._file.write(f"Task: {task_ref}\n")
            self._file.write(f"Started: {timestamp()}\n")
            self._file.write(f"{'═' * 60}\n\n")
            self._file.flush()

    def write(self, text: str):
        """Write text to log."""
        if self._file:
            self._file.write(text)
            self._file.flush()

    def write_footer(self, duration: str, result: str):
        """Write task footer."""
        if self._file:
            self._file.write(f"\n{'═' * 60}\n")
            self._file.write(f"Finished: {timestamp()}\n")
            self._file.write(f"Duration: {duration}\n")
            self._file.write(f"Result: {result}\n")
            self._file.write(f"{'═' * 60}\n")
            self._file.flush()
