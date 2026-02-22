"""Stream monitor for Claude JSON output."""

import json
import re
import sys
from dataclasses import dataclass
from typing import TextIO

from .errors import ErrorType, classify_from_json
from .logging import (
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    NC,
    RED,
    WHITE,
    YELLOW,
    timestamp_short,
)


@dataclass
class SessionStats:
    """Session statistics."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0

    def add_usage(self, usage: dict, cost: float = 0.0):
        """Add usage data from result."""
        self.input_tokens += usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_read += usage.get("cache_read_input_tokens", 0)
        self.cost_usd += cost


@dataclass
class StreamResult:
    """Result of processing stream."""

    error_type: ErrorType
    stats: SessionStats
    session_id: str | None = None
    model: str | None = None


# Tool icons and formatters
TOOL_FORMATS = {
    "Read": ("📖", lambda i: _format_read(i)),
    "Edit": ("✏️", lambda i: _format_edit(i)),
    "Write": ("📝", lambda i: i.get("file_path", "")),
    "Bash": ("💻", lambda i: _format_bash(i)),
    "Grep": ("🔍", lambda i: f"{i.get('pattern', '')} in {i.get('path', '.')}"),
    "Glob": ("🔍", lambda i: i.get("pattern", "")),
    "Task": ("🤖", lambda i: i.get("description", "")),
    "TaskOutput": ("🔧", lambda i: "TaskOutput"),
    "TodoWrite": ("✅", lambda i: _format_todos(i)),
    "WebFetch": ("🌐", lambda i: i.get("url", "")),
    "WebSearch": ("🔎", lambda i: i.get("query", "")),
    "Skill": ("⚡", lambda i: f"/{i.get('skill', '')}"),
    "LSP": ("🔗", lambda i: f"{i.get('operation', '')} {i.get('filePath', '')}"),
}


def _format_edit(i: dict) -> str:
    """Format Edit tool with change size."""
    path = i.get("file_path", "")
    old_len = len(i.get("old_string", ""))
    new_len = len(i.get("new_string", ""))
    return f"{path} [-{old_len}/+{new_len}]"


def _format_todos(i: dict) -> str:
    """Format TodoWrite with task summary."""
    todos = i.get("todos", [])
    if not todos:
        return "todos cleared"

    in_progress = [t for t in todos if t.get("status") == "in_progress"]
    completed = sum(1 for t in todos if t.get("status") == "completed")
    pending = sum(1 for t in todos if t.get("status") == "pending")

    if in_progress:
        current = in_progress[0].get("activeForm", in_progress[0].get("content", "?"))
        return f"{current} ({completed}✓ {pending}○)"

    if completed == len(todos):
        return f"all {completed} tasks completed"

    return f"{completed}✓ {pending}○ tasks"


def _format_read(i: dict) -> str:
    """Format Read tool with optional line range."""
    path = i.get("file_path", "")
    offset = i.get("offset")
    limit = i.get("limit")

    if offset or limit:
        parts = []
        if offset:
            parts.append(f"from:{offset}")
        if limit:
            parts.append(f"lines:{limit}")
        return f"{path} ({', '.join(parts)})"
    return path


def _format_bash(i: dict) -> str:
    """Format Bash tool with description and command."""
    desc = i.get("description", "")
    cmd = i.get("command", "")
    bg = i.get("run_in_background", False)

    ITALIC = "\033[3m"
    RESET = "\033[0m"

    lines = []
    if desc:
        lines.append(f"{desc} [bg]" if bg else desc)

    if cmd:
        for line in cmd.strip().split("\n"):
            lines.append(f"   {ITALIC}{line}{RESET}")

    return "\n".join(lines) if lines else "[no command]"


def _format_mcp_tool(name: str, input_data: dict) -> str | None:
    """Format MCP tool calls."""
    if name.startswith("mcp__ralph-tasks__") or name.startswith("mcp__md-task-mcp__"):
        action = name.replace("mcp__ralph-tasks__", "").replace("mcp__md-task-mcp__", "")
        project = input_data.get("project", "")
        number = input_data.get("number", "")
        status = input_data.get("status", "")
        result = f"{CYAN}📋 {action} {project}#{number}"
        if status:
            result += f" → {status}"
        return result + NC
    elif name.startswith("mcp__"):
        short_name = name.replace("mcp__", "")
        return f"{CYAN}🔌 {short_name}{NC}"
    return None


def _format_tool(name: str, input_data: dict) -> str:
    """Format a tool call for display."""
    # Check MCP tools first
    mcp_result = _format_mcp_tool(name, input_data)
    if mcp_result:
        return mcp_result

    # Check known tools
    if name in TOOL_FORMATS:
        icon, formatter = TOOL_FORMATS[name]
        return f"{GREEN}{icon} {formatter(input_data)}{NC}"

    # Fallback
    return f"{GREEN}🔧 {name}{NC}"


class StreamMonitor:
    """Monitor and format Claude JSON stream output."""

    # Confirmation phrase that marks successful task completion
    CONFIRMATION_PHRASE = "I confirm that all task phases are fully completed"

    def __init__(
        self,
        output: TextIO = sys.stdout,
        log_file: TextIO | None = None,
        raw_json_file: TextIO | None = None,
    ):
        self.output = output
        self.log_file = log_file
        self.raw_json_file = raw_json_file  # For saving unprocessed JSON lines
        self.stats = SessionStats()
        self.session_id: str | None = None
        self.model: str | None = None
        self.error_type = ErrorType.COMPLETED
        self.confirmed = False  # True if confirmation phrase was found

    def _write(self, text: str, timestamp: bool = True):
        """Write formatted output."""
        if timestamp:
            prefix = f"{DIM}[{timestamp_short()}]{NC} "
            self.output.write(f"{prefix}{text}\n")
        else:
            self.output.write(f"{text}\n")
        self.output.flush()

        if self.log_file:
            # Strip ANSI for log file
            clean = re.sub(r"\033\[[0-9;]*m", "", text)
            self.log_file.write(f"[{timestamp_short()}] {clean}\n")
            self.log_file.flush()

    def _process_init(self, data: dict):
        """Process system init message."""
        self.model = data.get("model", "unknown")
        self.session_id = data.get("session_id", "")
        mcp_servers = data.get("mcp_servers", [])
        mcp_status = ", ".join(
            f"{s['name']}({'ok' if s.get('status') == 'connected' else 'fail'})"
            for s in mcp_servers
        )
        short_id = self.session_id[:8] if self.session_id else "none"
        self._write(
            f"{DIM}Session: {short_id} | Model: {self.model} | MCP: {mcp_status or 'none'}{NC}"
        )

    def _process_result(self, data: dict):
        """Process result message."""
        cost = data.get("total_cost_usd", 0)
        usage = data.get("usage", {})
        self.stats.add_usage(usage, cost)

        input_t = self.stats.input_tokens
        output_t = self.stats.output_tokens

        if data.get("is_error") or data.get("subtype") == "error_during_execution":
            error_type, detail = classify_from_json(data)
            # Log raw error data for diagnostics
            raw_error = {
                "result": data.get("result"),
                "error_code": data.get("error_code"),
                "errors": data.get("errors"),
            }
            # If confirmation phrase was found, treat as success despite error
            if self.confirmed:
                self._write(
                    f"{YELLOW}⚠ Post-completion error ignored: {detail} | Tokens: {input_t} in / {output_t} out{NC}"
                )
                self._write(f"{DIM}  Raw error: {raw_error}{NC}")
                # Keep error_type as COMPLETED
            else:
                self.error_type = error_type
                self._write(
                    f"{RED}❌ ERROR: {self.error_type.value} | {detail} | Tokens: {input_t} in / {output_t} out{NC}"
                )
                self._write(f"{DIM}  Raw error: {raw_error}{NC}")
        else:
            self._write(f"{MAGENTA}📊 {input_t:,} in / {output_t:,} out | ${cost:.2f}{NC}")

    def _process_assistant(self, data: dict):
        """Process assistant message."""
        message = data.get("message", {})
        content = message.get("content", [])

        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "").strip()
                if text:
                    self._write(f"{WHITE}{text}{NC}")
                    # Check for confirmation phrase
                    if self.CONFIRMATION_PHRASE in text:
                        self.confirmed = True
            elif item.get("type") == "tool_use":
                self.stats.tool_calls += 1
                name = item.get("name", "")
                input_data = item.get("input", {})
                self._write(_format_tool(name, input_data))

    def process_line(self, line: str):
        """Process a single JSON line."""
        # Save raw JSON for diagnostics
        if self.raw_json_file:
            self.raw_json_file.write(line + "\n")
            self.raw_json_file.flush()

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")

        if msg_type == "system" and data.get("subtype") == "init":
            self._process_init(data)
        elif msg_type == "result":
            self._process_result(data)
        elif msg_type == "assistant":
            self._process_assistant(data)

    def process_stream(self, stream: TextIO) -> StreamResult:
        """Process entire stream and return result."""
        for line in stream:
            line = line.strip()
            if line:
                self.process_line(line)

        return StreamResult(
            error_type=self.error_type,
            stats=self.stats,
            session_id=self.session_id,
            model=self.model,
        )

    def print_summary(self):
        """Print session statistics summary."""
        if self.stats.tool_calls == 0 and self.stats.input_tokens == 0:
            return

        self._write(f"\n{MAGENTA}{'═' * 50}{NC}", timestamp=False)
        self._write(f"{MAGENTA}SESSION TOTALS{NC}", timestamp=False)
        self._write(f"{MAGENTA}{'─' * 50}{NC}", timestamp=False)
        self._write(
            f"{MAGENTA}Tokens: {self.stats.input_tokens:,} in / {self.stats.output_tokens:,} out{NC}",
            timestamp=False,
        )
        if self.stats.cache_read > 0:
            cache_pct = (
                self.stats.cache_read / self.stats.input_tokens * 100
                if self.stats.input_tokens > 0
                else 0
            )
            self._write(
                f"{MAGENTA}Cache:  {self.stats.cache_read:,} ({cache_pct:.0f}%){NC}",
                timestamp=False,
            )
        self._write(f"{MAGENTA}Cost:   ${self.stats.cost_usd:.2f}{NC}", timestamp=False)
        self._write(f"{MAGENTA}Tools:  {self.stats.tool_calls}{NC}", timestamp=False)
        self._write(f"{MAGENTA}{'═' * 50}{NC}", timestamp=False)
