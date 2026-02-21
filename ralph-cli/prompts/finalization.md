Finalize task {task_ref} after all reviews are complete.

## Instructions

1. Get task details via ralph-tasks MCP: `tasks("{project}", {number})`
2. Run relevant tests to verify nothing is broken after review fixes
3. Run linters: `uv run ruff check .` and `uv run ruff format --check .`
4. Fix any test failures or linter issues
5. Squash any fixup commits: `git rebase -i --autosquash` (use GIT_SEQUENCE_EDITOR=true)
6. Update task status to done with a report

## Report Format

Update task via `update_task` with:
- `status`: "done"
- `completed`: current date (YYYY-MM-DD)
- `report`: Summary of all work done, changed files, test results

## Important

- Do NOT skip test verification
- Fix issues found during finalization
- Create a clean final commit if needed
- Write confirmation phrase before updating task:
  "I confirm that all task phases are fully completed."
