"""MCP role switching for ralph-tasks server.

Each CLI command registers ralph-tasks MCP with the appropriate role endpoint
before launching Claude, ensuring least-privilege access:

- SWE (/mcp-swe): update status/report/blocks, reply/decline findings
- Planner (/mcp-plan): update title/description/plan
- Reviewer (/mcp-review?review_type=X): add/resolve findings
"""

from __future__ import annotations

import logging
import re
import subprocess
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

_CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"

_MCP_BASE_URL = "http://ai-sbx-ralph-tasks:8000"
_MCP_SERVER_NAME = "ralph-tasks"


class McpRole(Enum):
    """Available MCP role endpoints."""

    SWE = "/mcp-swe"
    PLANNER = "/mcp-plan"

    def url(self, review_type: str | None = None) -> str:
        return f"{_MCP_BASE_URL}{self.value}"


class McpReviewerRole:
    """Reviewer role with required review_type parameter."""

    def __init__(self, review_type: str):
        self.review_type = review_type

    def url(self) -> str:
        return f"{_MCP_BASE_URL}/mcp-review?review_type={self.review_type}"


class McpRegistrationError(RuntimeError):
    """Raised when MCP role registration fails."""


def register_mcp(
    role: McpRole | McpReviewerRole,
    api_key: str | None = None,
) -> None:
    """Register ralph-tasks MCP with the given role endpoint.

    Raises McpRegistrationError on failure (fail-closed).
    """
    url = role.url() if isinstance(role, McpReviewerRole) else role.url()

    subprocess.run(
        ["claude", "mcp", "remove", _MCP_SERVER_NAME],
        capture_output=True,
    )
    cmd = ["claude", "mcp", "add", "-s", "user", "--transport", "http"]
    if api_key:
        cmd += ["--header", f"Authorization: Bearer {api_key}"]
    cmd += [_MCP_SERVER_NAME, url]
    result = subprocess.run(cmd, capture_output=True)

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise McpRegistrationError(
            f"Failed to register ralph-tasks MCP as {url}: {stderr}"
        )
    logger.debug("Registered ralph-tasks MCP: %s", url)


@contextmanager
def mcp_role(
    role: McpRole | McpReviewerRole,
    api_key: str | None = None,
):
    """Switch ralph-tasks MCP to the given role, restore SWE on exit.

    Raises McpRegistrationError if the initial switch fails (fail-closed).
    Restoration to SWE is best-effort — logged but not re-raised.
    """
    register_mcp(role, api_key)
    try:
        yield
    finally:
        try:
            register_mcp(McpRole.SWE, api_key)
        except McpRegistrationError:
            logger.error("Failed to restore SWE MCP role — manual fix may be needed")


# ---------------------------------------------------------------------------
# Codex config.toml MCP switching
# ---------------------------------------------------------------------------

# Matches the ralph-tasks URL line in codex config.toml:
#   url = "http://ai-sbx-ralph-tasks:8000/mcp-swe"
_CODEX_URL_RE = re.compile(
    r'(url\s*=\s*")http://ai-sbx-ralph-tasks:8000/[^"]*(")'
)


@contextmanager
def codex_mcp_role(role: McpReviewerRole):
    """Switch Codex config.toml ralph-tasks URL, restore on exit.

    Codex has its own MCP config (~/.codex/config.toml), independent from
    Claude's ``claude mcp add/remove``.  This context manager patches the URL
    for the duration of the codex subprocess, then restores the original.

    Raises McpRegistrationError if the config file is missing or URL not found.
    """
    config = _CODEX_CONFIG_PATH
    if not config.exists():
        raise McpRegistrationError(f"Codex config not found: {config}")

    original = config.read_text()
    patched = _CODEX_URL_RE.sub(rf"\1{role.url()}\2", original)

    if patched == original:
        raise McpRegistrationError(
            f"ralph-tasks URL not found in {config} — cannot switch MCP role"
        )

    config.write_text(patched)
    logger.debug("Patched codex config MCP URL: %s", role.url())

    try:
        yield
    finally:
        config.write_text(original)
        logger.debug("Restored codex config MCP URL")
