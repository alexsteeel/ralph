"""Fire-and-forget metrics submission to ralph-tasks API."""

import json
import logging
import urllib.request
from datetime import datetime

from .config import get_settings

logger = logging.getLogger(__name__)


def submit_session_metrics(
    *,
    command_type: str,
    project: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    total_cost_usd: float = 0.0,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    total_cache_read: int = 0,
    total_tool_calls: int = 0,
    exit_code: int | None = None,
    error_type: str | None = None,
    model: str | None = None,
    claude_session_id: str | None = None,
    task_executions: list[dict] | None = None,
) -> bool:
    """Submit session metrics to ralph-tasks API.

    Fire-and-forget: logs warnings on failure, never raises.
    Returns True on successful submission, False if not configured or on error.
    """
    settings = get_settings()
    api_url = settings.ralph_tasks_api_url

    if not api_url:
        return False

    payload: dict = {
        "command_type": command_type,
        "project": project,
        "started_at": started_at.isoformat(),
        "total_cost_usd": total_cost_usd,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read": total_cache_read,
        "total_tool_calls": total_tool_calls,
    }

    if finished_at is not None:
        payload["finished_at"] = finished_at.isoformat()
    if exit_code is not None:
        payload["exit_code"] = exit_code
    if error_type is not None:
        payload["error_type"] = error_type
    if model is not None:
        payload["model"] = model
    if claude_session_id is not None:
        payload["claude_session_id"] = claude_session_id
    if task_executions is not None:
        payload["task_executions"] = task_executions

    url = f"{api_url.rstrip('/')}/api/metrics/sessions"
    headers = {"Content-Type": "application/json"}

    api_key = settings.ralph_tasks_api_key
    if api_key:
        if not url.startswith("https://"):
            logger.warning("Sending API key over non-HTTPS connection to %s", url)
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            ok = result.get("ok", False)
            if not ok:
                logger.warning("Metrics server rejected submission: %s", result)
            return ok
    except Exception as e:
        logger.warning("Failed to submit metrics: %s", e)
        return False
