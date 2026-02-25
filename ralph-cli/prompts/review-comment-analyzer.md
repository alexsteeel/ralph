Review comments for task {task_ref}.

1. Get task context: `tasks("{project}", {number})` via ralph-tasks MCP
2. Read the task plan to understand requirements
3. Determine the diff scope:
   - If base_commit is provided (`{base_commit}`), use: `git diff {base_commit}..HEAD`
   - Otherwise, use: `git diff HEAD~1`
4. Read changed files in full for context

Now launch the specialized comment analysis agent:

Use the Task tool with subagent_type="pr-review-toolkit:comment-analyzer" to analyze comments in the changed code. In the prompt, provide:
- The diff output and full changed files
- Instruction to check: comment accuracy vs actual code, outdated comments, misleading descriptions, missing documentation for complex logic, comment rot risks

5. For each issue found, call `add_review_finding` ralph-tasks MCP tool:
   - project: "{project}", number: {number}
   - review_type: "{review_type}", author: "{author}"
   - Include file path and line numbers (file, line_start, line_end)
6. If no issues found — do NOT create any findings

Do NOT modify any code — only analyze and write findings.
