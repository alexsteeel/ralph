Security review for task {task_ref}.

1. Get task context: `tasks("{project}", {number})` via ralph-tasks MCP
2. Determine the diff scope:
   - If base_commit is provided (`{base_commit}`), use: `git diff {base_commit}..HEAD`
   - Otherwise, use: `git diff HEAD~1`
3. Read changed files in full for context

Now launch the specialized code review agent with security focus:

Use the Task tool with subagent_type="feature-dev:code-reviewer" to perform a security-focused review. In the prompt, provide:
- The diff output and full changed files
- Instruction to focus exclusively on security vulnerabilities: injection (SQL, command, XSS, path traversal), hardcoded secrets/credentials, authentication/authorization gaps, CSRF issues, insecure deserialization, missing input validation at system boundaries, error messages leaking sensitive data
- Ignore code style, naming, and non-security concerns

5. For each issue found, call `add_review_finding` ralph-tasks MCP tool:
   - project: "{project}", number: {number}
   - review_type: "{review_type}", author: "{author}"
   - Include file path and line numbers (file, line_start, line_end)
6. If no issues found — do NOT create any findings

Focus on exploitable vulnerabilities, not theoretical risks.
Do NOT modify any code — only analyze and write findings.
