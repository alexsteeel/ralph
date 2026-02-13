#!/usr/bin/env python3
"""
Enforce Isolated Skills Hook

Blocks direct Skill calls for tools that must run in isolated context (via Task).
These skills consume too much context when run directly.

Blocked skills:
- pr-review-toolkit:review-pr → use Task(subagent_type="pr-review-toolkit:review-pr")
- security-review → use Task(subagent_type="general-purpose", prompt="/security-review ...")
"""

import json
import sys

from hook_utils import get_logger

log = get_logger("enforce_isolated_skills")

# Skills that MUST be called via Task tool (isolated context)
ISOLATED_SKILLS = {
    # pr-review-toolkit agents (all must be isolated)
    "pr-review-toolkit:review-pr": "Task(subagent_type='pr-review-toolkit:review-pr', ...)",
    "pr-review-toolkit:code-reviewer": "Task(subagent_type='pr-review-toolkit:code-reviewer', ...)",
    "pr-review-toolkit:silent-failure-hunter": "Task(subagent_type='pr-review-toolkit:silent-failure-hunter', ...)",
    "pr-review-toolkit:type-design-analyzer": "Task(subagent_type='pr-review-toolkit:type-design-analyzer', ...)",
    "pr-review-toolkit:pr-test-analyzer": "Task(subagent_type='pr-review-toolkit:pr-test-analyzer', ...)",
    "pr-review-toolkit:comment-analyzer": "Task(subagent_type='pr-review-toolkit:comment-analyzer', ...)",
    "review-pr": "Task(subagent_type='pr-review-toolkit:review-pr', ...)",
    # code-simplifier
    "code-simplifier:code-simplifier": "Task(subagent_type='code-simplifier:code-simplifier', ...)",
    # built-in skills
    "security-review": "Task(subagent_type='general-purpose', prompt='/security-review ...')",
    # NOTE: codex-review removed - codex is called directly via codex CLI
}


def handle_pre_tool_use(hook_input: dict) -> int:
    """Block Skill calls for tools that must use isolated context."""
    tool_input = hook_input.get("tool_input", {})

    # Get skill name from tool input
    skill_name = tool_input.get("skill", "")

    if not skill_name:
        return 0  # Not a skill call

    # Check if this skill should be isolated
    if skill_name in ISOLATED_SKILLS:
        alternative = ISOLATED_SKILLS[skill_name]
        reason = f"""🚫 SKILL BLOCKED: {skill_name}

This skill must run in ISOLATED context to avoid context overflow.

❌ WRONG: Skill(skill="{skill_name}")
✅ RIGHT: {alternative}

The skill consumes too much context when run directly.
Use Task tool with appropriate subagent_type instead.
"""
        response = {"decision": "block", "reason": reason}
        print(json.dumps(response))

        log("BLOCKED", skill_name)
        return 2  # Block the tool call

    return 0  # Allow other skills


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            return 0

        hook_input = json.loads(input_data)
        event = hook_input.get("hook_event_name", "")

        if event == "PreToolUse":
            return handle_pre_tool_use(hook_input)

        return 0
    except Exception as e:
        log("ERROR", str(e))
        return 0


if __name__ == "__main__":
    sys.exit(main())
