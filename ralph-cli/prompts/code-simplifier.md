Simplify code for task {task_ref}.

1. Get task details via ralph-tasks MCP: `tasks("{project}", {number})`
2. Read the task plan to understand what was implemented
3. Determine the diff scope:
   - If base_commit is provided (`{base_commit}`), use: `git diff {base_commit}..HEAD`
   - Otherwise, use: `git diff HEAD~1`
4. Read changed files in full

Now launch the specialized code simplifier agent:

Use the Task tool with subagent_type="code-simplifier:code-simplifier" to simplify the changed code. In the prompt, provide:
- The full content of changed files
- The diff for reference
- Instruction to simplify: overly complex conditionals, duplicated code, unnecessary abstractions, verbose patterns with simpler equivalents, inconsistent naming, dead code/unused imports

## Rules

- Preserve ALL existing functionality — no behavior changes
- Follow existing project patterns and conventions
- Do NOT add new features or capabilities
- Do NOT add comments unless the logic is truly non-obvious
- Do NOT create a commit — ralph CLI handles commits
- Focus only on files changed in the diff scope
