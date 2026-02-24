"""Config display command."""

from __future__ import annotations

import json
import sys

from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape

from ..config import Settings, get_settings

console = Console()

# Fields that contain secrets and should be masked
_SECRET_KEYWORDS = ("token", "secret", "password", "api_key", "chat_id")

# Display sections: (section_title, field_names)
SECTIONS: list[tuple[str, list[str]]] = [
    (
        "Telegram",
        ["telegram_bot_token", "telegram_chat_id", "telegram_configured"],
    ),
    (
        "Recovery",
        ["recovery_enabled", "recovery_delays", "context_overflow_max_retries"],
    ),
    (
        "Timeouts",
        ["health_check_timeout", "review_timeout"],
    ),
    (
        "Review",
        ["claude_review_model", "code_review_max_iterations", "security_review_max_iterations"],
    ),
    (
        "Codex",
        ["codex_review_max_iterations", "codex_review_model", "codex_plan_review_enabled"],
    ),
    (
        "Metrics",
        ["ralph_tasks_api_url", "ralph_tasks_api_key"],
    ),
    (
        "Paths",
        ["log_dir"],
    ),
]


def _is_secret(field_name: str) -> bool:
    """Check if a field name indicates a secret value."""
    return any(kw in field_name for kw in _SECRET_KEYWORDS)


def _mask_value(value: object) -> str:
    """Mask a secret value, showing only last 3 characters.

    Returns '(not set)' if value is None.
    """
    if value is None:
        return "(not set)"
    s = str(value)
    if len(s) <= 3:
        return "****"
    return f"****{s[-3:]}"


def _format_value(value: object) -> str:
    """Format a value for display."""
    if value is None:
        return "(not set)"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _get_config_dict(settings: Settings) -> dict[str, object]:
    """Build config dict from settings, including computed properties."""
    data = settings.model_dump()
    # @property fields are excluded by model_dump(); add them explicitly
    data["telegram_configured"] = settings.telegram_configured
    # Convert Path objects to strings for JSON serialization
    return {k: str(v) if hasattr(v, "__fspath__") else v for k, v in data.items()}


def _masked_config_dict(config: dict[str, object]) -> dict[str, object]:
    """Return config dict with secret values masked."""
    return {k: _mask_value(v) if _is_secret(k) and v is not None else v for k, v in config.items()}


def run_config(key: str | None = None, json_output: bool = False) -> int:
    """Display current configuration.

    Returns exit code: 0 on success, 1 if key not found.
    """
    try:
        settings = get_settings()
    except ValidationError as e:
        print(f"Configuration validation failed. Check ~/.claude/.env\n{e}", file=sys.stderr)
        return 1

    config = _get_config_dict(settings)
    masked = _masked_config_dict(config)

    # Single key mode
    if key is not None:
        if key not in config:
            print(f"Unknown config key: {key}", file=sys.stderr)
            return 1
        value = masked[key]
        if json_output:
            print(json.dumps({key: value}, default=str))
        elif _is_secret(key) and config[key] is not None:
            print(value)
        else:
            print(_format_value(value))
        return 0

    # Full output — JSON mode
    if json_output:
        print(json.dumps(masked, indent=2, default=str))
        return 0

    # Full output — rich table
    env_file = settings.model_config.get("env_file", "~/.claude/.env")
    console.print()
    console.print("[bold]Ralph CLI Configuration[/bold]")
    console.print("━" * 40)
    console.print(f"Source: {escape(str(env_file))}")
    console.print()

    for section_title, fields in SECTIONS:
        console.print(f"[bold cyan]{section_title}[/bold cyan]")
        for field in fields:
            if field not in config:
                continue
            raw = config[field]
            if _is_secret(field) and raw is not None:
                display = _mask_value(raw)
            else:
                display = _format_value(raw)
            console.print(f"  {field + ':':<40} {escape(display)}")
        console.print()

    return 0
