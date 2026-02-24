"""MCP role endpoints for ralph-tasks.

Three separate FastMCP instances, each with a distinct tool set:
- ``/mcp-swe``    — developer tools (full task + attachments, review read/reply/decline)
- ``/mcp-review`` — reviewer tools (read-only tasks, create/reply/resolve findings)
- ``/mcp-plan``   — planner tools (task CRUD incl. title/description/plan, read-only findings)
"""

from starlette.applications import Starlette

from .planner import mcp as _planner_mcp
from .reviewer import mcp as _reviewer_mcp
from .swe import mcp as _swe_mcp


def get_swe_mcp_app() -> Starlette:
    """Return ASGI app for SWE role MCP endpoint."""
    return _swe_mcp.http_app(path="/", transport="streamable-http")


def get_reviewer_mcp_app() -> Starlette:
    """Return ASGI app for Reviewer role MCP endpoint."""
    return _reviewer_mcp.http_app(path="/", transport="streamable-http")


def get_planner_mcp_app() -> Starlette:
    """Return ASGI app for Planner role MCP endpoint."""
    return _planner_mcp.http_app(path="/", transport="streamable-http")
