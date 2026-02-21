Review the code for task {task_ref}.

1. Get task details via MCP: tasks("{project}", {number})
2. Read the task plan and body to understand requirements
3. Analyze the latest commit (git log -1 -p, git diff HEAD~1)
4. If there is frontend — check UI via playwright MCP
5. Write findings via add_review_finding MCP tool

For each issue, call add_review_finding with:
- project: "{project}"
- number: {number}
- review_type: "codex-review"
- text: Clear description of the issue
- author: "codex-reviewer"
- file: File path (if applicable)
- line_start/line_end: Line numbers (if applicable)

Severity levels: CRITICAL / HIGH / MEDIUM / LOW
If no issues — write a finding with text "LGTM — no issues found".

Do NOT modify code — only analyze and write findings.
