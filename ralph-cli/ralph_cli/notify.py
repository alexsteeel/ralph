"""Telegram notifications for Ralph."""

import json
import sys
import urllib.request
from datetime import datetime

from .config import get_settings


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown.

    Escapes all Markdown special characters to prevent parse errors.
    """
    # Order matters: escape backslash first
    for char in [
        "\\",
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    ]:
        text = text.replace(char, f"\\{char}")
    return text


def send_telegram(token: str, chat_id: str, message: str) -> bool:
    """Send message to Telegram.

    Returns True on success, False on failure.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"Telegram error: {e}", file=sys.stderr)
        return False


class Notifier:
    """Telegram notifier.

    Disables itself after first connection failure to avoid
    spamming errors when Telegram is unreachable (e.g. filtered proxy).
    """

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        """Initialize notifier.

        If token/chat_id not provided, loads from config.
        """
        if token is None or chat_id is None:
            settings = get_settings()
            token = token or settings.telegram_bot_token
            chat_id = chat_id or settings.telegram_chat_id

        self.token = token
        self.chat_id = chat_id
        self._disabled = False

    @property
    def is_configured(self) -> bool:
        """Check if notifications are configured."""
        return bool(self.token and self.chat_id)

    def _send(self, message: str) -> bool:
        """Send message if configured and reachable."""
        if not self.is_configured or self._disabled:
            return False
        result = send_telegram(self.token, self.chat_id, message)
        if not result:
            self._disabled = True
        return result

    def session_start(self, project: str, tasks: list[int]) -> bool:
        """Notify session start."""
        task_str = ", ".join(str(t) for t in tasks)

        message = f"""🚀 *RALPH STARTED*

*Project:* {escape_markdown(project)}
*Tasks:* {len(tasks)} ({task_str})
*Time:* {datetime.now().strftime("%H:%M")}"""
        return self._send(message)

    def task_failed(self, task_ref: str, reason: str) -> bool:
        """Notify task failure."""
        message = f"""⚠️ Task {task_ref} failed: {escape_markdown(reason)}"""
        return self._send(message)

    def recovery_start(self, attempt: int, max_attempts: int, delay: int) -> bool:
        """Notify recovery start."""
        delay_min = delay // 60
        message = f"""🔄 *API error detected*
Recovery attempt {attempt}/{max_attempts} in {delay_min} min"""
        return self._send(message)

    def recovery_success(self, task_ref: str) -> bool:
        """Notify recovery success."""
        message = f"""✅ *API recovered*
Resuming task {task_ref}"""
        return self._send(message)

    def pipeline_stopped(self, reason: str) -> bool:
        """Notify pipeline stopped."""
        message = f"""🚨 *PIPELINE STOPPED*

*Reason:* {escape_markdown(reason)}
*Time:* {datetime.now().strftime("%H:%M")}"""
        return self._send(message)

    def session_complete(
        self,
        project: str,
        duration: str,
        completed: list[int],
        failed: list[int],
        failed_reasons: list[str] | None = None,
        durations: dict[int, str] | None = None,
        total_cost_usd: float = 0.0,
        task_costs: dict[int, float] | None = None,
        project_stats: dict[str, int] | None = None,
    ) -> bool:
        """Notify session completion with extended stats.

        Args:
            project: Project name
            duration: Total session duration
            completed: List of completed task numbers
            failed: List of failed task numbers
            failed_reasons: Reasons for each failure
            durations: Duration for each task
            total_cost_usd: Total cost for all tasks
            task_costs: Cost for each individual task
            project_stats: Task status counts from project (e.g., {'done': 5, 'work': 1})
        """
        lines = [
            "📊 *RALPH SESSION COMPLETE*",
            "",
            f"*Project:* {escape_markdown(project)}",
            f"*Duration:* {duration}",
            f"*Total cost:* ${total_cost_usd:.2f}",
        ]

        if completed:
            lines.append("")
            lines.append(f"✅ *Completed ({len(completed)}):*")
            for task in completed:
                dur = durations.get(task, "") if durations else ""
                cost = task_costs.get(task, 0.0) if task_costs else 0.0
                parts = []
                if dur:
                    parts.append(dur)
                if cost > 0:
                    parts.append(f"${cost:.2f}")
                suffix = f" ({', '.join(parts)})" if parts else ""
                lines.append(f"• #{task}{suffix}")

        if failed:
            lines.append("")
            lines.append(f"❌ *Failed ({len(failed)}):*")
            for i, task in enumerate(failed):
                reason = (
                    failed_reasons[i] if failed_reasons and i < len(failed_reasons) else "UNKNOWN"
                )
                lines.append(f"• #{task} — {escape_markdown(reason)}")

        # Add project task status summary
        if project_stats:
            lines.append("")
            lines.append("📋 *Project status:*")
            status_order = ["done", "approved", "work", "todo", "hold"]
            status_icons = {
                "done": "✅",
                "approved": "✅",
                "work": "🔄",
                "todo": "📝",
                "hold": "⏸️",
            }
            for status in status_order:
                count = project_stats.get(status, 0)
                if count > 0:
                    icon = status_icons.get(status, "•")
                    lines.append(f"{icon} {status}: {count}")

        return self._send("\n".join(lines))

    def review_failed(
        self, task_ref: str, review_name: str, reason: str, log_path: str = ""
    ) -> bool:
        """Notify review failure (codex or other)."""
        lines = [
            "🚨 *REVIEW FAILED*",
            "",
            f"*Task:* {task_ref}",
            f"*Review:* {escape_markdown(review_name)}",
            f"*Reason:* {escape_markdown(reason)}",
            f"*Time:* {datetime.now().strftime('%H:%M')}",
        ]
        if log_path:
            lines.append(f"*Log:* {escape_markdown(log_path)}")
        return self._send("\n".join(lines))

    def context_overflow(self, task_ref: str, retry: int, max_retries: int) -> bool:
        """Notify context overflow retry."""
        message = f"""⚠️ *Context overflow* on task {task_ref}
Retry {retry}/{max_retries} with fresh session"""
        return self._send(message)

    def task_complete(
        self,
        task_ref: str,
        duration: str,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        status: str | None = None,
    ) -> bool:
        """Notify single task completion with stats."""
        status_icons = {
            "done": "✅",
            "approved": "✅",
            "work": "🔄",
            "todo": "📝",
            "hold": "⏸️",
        }
        status_line = ""
        if status:
            icon = status_icons.get(status, "•")
            status_line = f"\n*Status:* {icon} {status}"

        message = f"""✅ *Task {task_ref} completed*

*Duration:* {duration}
*Cost:* ${cost_usd:.2f}
*Tokens:* {input_tokens:,} in / {output_tokens:,} out{status_line}"""
        return self._send(message)
