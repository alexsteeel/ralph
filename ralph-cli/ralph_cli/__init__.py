"""Ralph CLI — Autonomous task execution for Claude Code."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ralph-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"
