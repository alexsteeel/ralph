#!/usr/bin/env python3
"""
Workflow Task Verification Hook

Simple confirmation-based workflow control for /execute-python-task.
Blocks stop until Claude confirms completion with specific phrase.
"""

import json
import os
import sys
from pathlib import Path

from hook_utils import get_logger

log = get_logger("check_workflow")

STATE_DIR = Path.home() / ".claude" / "workflow-state"
ACTIVE_TASK_FILE = STATE_DIR / "active_task.txt"

CONFIRMATION_PHRASE = "i confirm that all task phases are fully completed"

CHECKLIST = """
## Checklist for /execute-python-task

### Planning
- [ ] Задача получена из ralph-tasks
- [ ] Plan Mode выполнен (EnterPlanMode → анализ → ExitPlanMode)
- [ ] План одобрен пользователем

### Testing (Initial)
- [ ] Unit tests написаны и проходят
- [ ] API tests написаны (если есть endpoints)
- [ ] UI tests написаны (если есть frontend)
- [ ] Edge cases покрыты тестами
- [ ] Existing tests не сломаны

### Reviews
- [ ] `/pr-review-toolkit:review-pr` выполнен
- [ ] `/security-review` выполнен
- [ ] `/codex-review` выполнен
- [ ] Все review записаны в задачу
- [ ] Все замечания исправлены ИЛИ отмечено почему некорректны

### Testing (Final)
- [ ] Все тесты проходят после исправлений

### Finalization
- [ ] Linters проходят (ruff, djlint)
- [ ] Cleanup выполнен (мусор удалён, разрешения проверены)
- [ ] Report записан в задачу (status=done)
- [ ] Отчёт показан пользователю
- [ ] Отчёт одобрен пользователем

📖 Command reference: /execute-python-task
"""


def get_active_task() -> str | None:
    """Get currently active task reference."""
    if ACTIVE_TASK_FILE.exists():
        return ACTIVE_TASK_FILE.read_text().strip()
    return None


def set_active_task(task_ref: str):
    """Set currently active task reference."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_TASK_FILE.write_text(task_ref)


def clear_active_task():
    """Clear active task when workflow completes."""
    ACTIVE_TASK_FILE.unlink(missing_ok=True)


def extract_task_ref(prompt: str) -> str | None:
    """Extract task reference like 'project#N' from prompt."""
    import re
    match = re.search(r'([a-zA-Z0-9_-]+#\d+)', prompt)
    return match.group(1) if match else None


def get_last_assistant_message(transcript_path: str) -> str:
    """Read the last assistant message from transcript file."""
    try:
        path = Path(transcript_path)
        if not path.exists():
            return ""

        last_assistant_msg = ""
        with path.open() as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("type") == "assistant":
                        message = entry.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                last_assistant_msg = block.get("text", "")
                except json.JSONDecodeError:
                    continue
        return last_assistant_msg
    except Exception:
        return ""


def handle_prompt_submit(hook_input: dict):
    """Check if workflow is starting."""
    prompt = hook_input.get("prompt", "")

    if "execute-python-task" in prompt.lower():
        task_ref = extract_task_ref(prompt)
        if task_ref:
            set_active_task(task_ref)
            log("WORKFLOW_START", task_ref)


def handle_stop(hook_input: dict):
    """Block stop if confirmation phrase not found."""
    transcript_path = hook_input.get("transcript_path", "")
    last_message = get_last_assistant_message(transcript_path) if transcript_path else ""

    task_ref = get_active_task()
    if not task_ref:
        return 0  # No active workflow, allow stop

    # Check for confirmation phrase
    if CONFIRMATION_PHRASE in last_message.lower():
        clear_active_task()
        log("WORKFLOW_CONFIRMED", task_ref)
        return 0  # Allow stop

    # Check for "need feedback" bypass (user interaction needed)
    if "need feedback" in last_message.lower():
        log("NEED_FEEDBACK", task_ref)
        return 0

    # Check if in Plan Mode (waiting for user approval)
    # This is detected by presence of plan-related content without exit
    if "exitplanmode" not in last_message.lower() and "plan" in last_message.lower():
        # Might be in plan mode, allow stop for user feedback
        pass  # Continue to block check

    # Block - confirmation not found
    reason = "⚠️ Workflow not confirmed complete.\n\n"
    reason += f"Task: {task_ref}\n\n"
    reason += "To complete the workflow, verify all items and write:\n"
    reason += "```\nI confirm that all task phases are fully completed.\n```\n\n"
    reason += CHECKLIST

    response = {"decision": "block", "reason": reason}
    print(json.dumps(response))

    log("BLOCKED", f"confirmation not found for {task_ref}")
    return 2


def main():
    # Only activate when WORKSPACE env var is set
    if not os.environ.get("WORKSPACE"):
        return 0

    try:
        input_data = sys.stdin.read()
        if not input_data:
            return 0

        hook_input = json.loads(input_data)
        event = hook_input.get("hook_event_name", "")

        if event == "UserPromptSubmit":
            handle_prompt_submit(hook_input)
            return 0
        elif event == "Stop":
            return handle_stop(hook_input)

        return 0
    except Exception as e:
        log("ERROR", str(e))
        return 0


if __name__ == "__main__":
    sys.exit(main())
