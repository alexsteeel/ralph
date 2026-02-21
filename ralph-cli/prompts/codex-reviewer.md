Review the code for task {task_ref}.

1. Get task details via MCP: tasks("{project}", {number})
2. Read the task plan and body to understand requirements
3. Determine the diff scope:
   - If base_commit is provided (`{base_commit}`), use: `git diff {base_commit}..HEAD`
   - Otherwise, use: `git diff HEAD~1`
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
If no issues found — do NOT create any findings.

Do NOT modify code — only analyze and write findings.
