#!/usr/bin/env python3
"""
Ralph Autonomous Workflow Hook

Simple confirmation-based workflow control for /ralph-implement-python-task.
Differences from check_workflow.py:
- No "need feedback" bypass (autonomous mode)
- Allows stop on hold (## Blocks + status=hold)
"""

import json
import os
import re
import sys
from pathlib import Path

from hook_utils import get_logger

log = get_logger("check_workflow_ralph")

STATE_DIR = Path.home() / ".claude" / "workflow-state"
ACTIVE_TASK_FILE = STATE_DIR / "active_ralph_task.txt"

CONFIRMATION_PHRASE = "i confirm that all task phases are fully completed"

CHECKLIST = """
## 🚨 PRODUCTION QUALITY CHECKLIST

**Это PRODUCTION код, НЕ MVP!** Все пункты ОБЯЗАТЕЛЬНЫ.

### Preparation
- [ ] Задача получена и содержит `## Plan`
- [ ] Статус задачи = work
- [ ] TodoWrite создан для отслеживания фаз (0-10)
- [ ] Файлы из Scope прочитаны

### Implementation
- [ ] Implementation выполнен ПОЛНОСТЬЮ по плану (не упрощён)

### Testing (Initial) — ВСЕ тесты должны проходить
- [ ] Unit tests написаны и проходят
- [ ] API tests написаны (если есть endpoints)
- [ ] UI tests написаны с data-testid (если есть frontend)
- [ ] Edge cases покрыты тестами
- [ ] Existing tests не сломаны
- [ ] **НЕТ skipped тестов** (skip = fail, исправь тест!)

### UI Review (если есть frontend)
- [ ] Визуальный анализ через Opus + playwright выполнен
- [ ] Проблемы UI исправлены (перекрытия, вёрстка, юзабилити)

### Testing (Final)
- [ ] Связанные тесты проходят после исправлений
- [ ] Финальная UI проверка выполнена (если frontend)

### Finalization — код должен быть чистым
- [ ] ВСЕ ошибки linters исправлены (ruff, djlint)
- [ ] Cleanup выполнен (мусор удалён, разрешения проверены)
- [ ] Коммит создан
- [ ] Report с commit hash записан в задачу (status=done)
- [ ] Финальный отчёт выведен

📖 Command reference: /ralph-implement-python-task

⚠️ ЗАПРЕЩЕНО: пропускать фазы, оставлять failing tests, игнорировать замечания.
⚠️ ЗАПРЕЩЕНО: помечать тесты как skip чтобы обойти падающие тесты!
⚠️ Если не можешь выполнить качественно → hold + ## Blocks.
"""

# Note: @pytest.mark.skipif is ALLOWED (conditional skip for platform/version)
# Only unconditional @pytest.mark.skip is blocked


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
    match = re.search(r"([a-zA-Z0-9_-]+#\d+)", prompt)
    return match.group(1) if match else None


def get_all_assistant_messages(transcript_path: str) -> str:
    """Read ALL assistant messages from transcript file (concatenated)."""
    try:
        path = Path(transcript_path)
        if not path.exists():
            return ""

        all_messages = []
        with path.open() as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("type") == "assistant":
                        message = entry.get("message", {})
                        content = message.get("content", [])
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    all_messages.append(text)
                except json.JSONDecodeError:
                    continue
        return "\n".join(all_messages)
    except Exception:
        return ""


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


def check_skipped_tests_in_repo(working_dir: str | None = None) -> list[str]:
    """Check repository for @pytest.mark.skip decorators.

    Searches test files directly - much more reliable than parsing transcript.
    Only detects unconditional @pytest.mark.skip, NOT @pytest.mark.skipif.
    Returns list of files:line with skip decorators.
    """
    import subprocess

    if not working_dir:
        working_dir = Path.cwd()
    else:
        working_dir = Path(working_dir)

    matches = []

    try:
        # Find all @pytest.mark.skip in Python test files
        result = subprocess.run(
            ["grep", "-r", "-n", "--include=*.py", "@pytest.mark.skip"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                # Skip lines with skipif (conditional skip is allowed)
                if "skipif" in line.lower():
                    continue
                # Skip this hook file itself (contains skip references in
                # comments, docstrings, and grep commands)
                if "check_workflow_ralph.py" in line:
                    continue
                # Only include test files
                if "test" in line.lower():
                    # Format: file:line:content -> take file:line
                    parts = line.split(":", 2)
                    if len(parts) >= 2:
                        matches.append(f"{parts[0]}:{parts[1]}")
    except (subprocess.TimeoutExpired, Exception):
        pass

    return matches[:10]  # Limit to 10 matches


def handle_prompt_submit(hook_input: dict):
    """Check if ralph workflow is starting."""
    prompt = hook_input.get("prompt", "")

    if "ralph-implement-python-task" in prompt.lower():
        task_ref = extract_task_ref(prompt)
        if task_ref:
            set_active_task(task_ref)
            log("WORKFLOW_START", task_ref)


def handle_stop(hook_input: dict):
    """Block stop unless confirmed or on hold."""
    transcript_path = hook_input.get("transcript_path", "")
    working_dir = hook_input.get("cwd", "")

    task_ref = get_active_task()
    if not task_ref:
        return 0  # No active workflow, allow stop

    # Search in ALL messages (not just last) for confirmation phrase
    all_messages = get_all_assistant_messages(transcript_path) if transcript_path else ""
    last_message = get_last_assistant_message(transcript_path) if transcript_path else ""

    # Check for confirmation phrase in ANY message
    if CONFIRMATION_PHRASE in all_messages.lower():
        # Check for skipped tests in repository - this is NOT allowed
        skipped_tests = check_skipped_tests_in_repo(working_dir)
        if skipped_tests:
            skip_list = "\n".join(f"- `{m}`" for m in skipped_tests[:10])
            reason = f"""🚨 SKIPPED TESTS FOUND IN REPOSITORY

Task: {task_ref}

**Файлы с @pytest.mark.skip:**
{skip_list}

⚠️ **SKIPPED = FAILED!**

Пропуск тестов через `@pytest.mark.skip` ЗАПРЕЩЁН.
Исправь падающие тесты вместо их пропуска.

Разрешённые исключения:
- Тесты, требующие внешней инфраструктуры (CI, staging)
- Тесты с `skipif` по условию (Python version, platform)

Удали skip декораторы или hold + ## Blocks с обоснованием."""

            response = {"decision": "block", "reason": reason}
            print(json.dumps(response))
            log("BLOCKED_SKIPPED_TESTS", f"{task_ref}: {skipped_tests[:3]}")
            return 2

        clear_active_task()
        log("WORKFLOW_CONFIRMED", task_ref)
        return 0  # Allow stop

    # Check for hold status in last message (## Blocks recorded)
    if "## blocks" in last_message.lower() or 'status="hold"' in last_message.lower():
        clear_active_task()
        log("WORKFLOW_HOLD", task_ref)
        return 0  # Allow stop when on hold

    # Block - confirmation not found
    reason = f"""🚨 PRODUCTION WORKFLOW NOT CONFIRMED

Task: {task_ref}

⚠️ Это PRODUCTION код, НЕ MVP! Все этапы ОБЯЗАТЕЛЬНЫ.

To complete the workflow, verify ALL items and write:
```
I confirm that all task phases are fully completed.
```

If blocked, commit WIP changes, record issue in ## Blocks and set status='hold'.

{CHECKLIST}"""

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
