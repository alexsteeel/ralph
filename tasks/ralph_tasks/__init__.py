"""Ralph Tasks — Markdown-based task management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ralph-tasks")
except PackageNotFoundError:
    __version__ = "0.0.0"
