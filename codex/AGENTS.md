# Ralph Monorepo

## Project Structure

uv workspace monorepo with 3 Python packages (flat layout, no `src/`):

| Directory | Package | Import | CLI |
|-----------|---------|--------|-----|
| `tasks/` | `ralph-tasks` | `from ralph_tasks.core import ...` | `tm`, `tm-web` |
| `sandbox/` | `ralph-sandbox` | `from ralph_sandbox.cli import ...` | `ai-sbx` |
| `ralph-cli/` | `ralph-cli` | `from ralph_cli.cli import ...` | `ralph` |

Non-package directories:
- `claude/` — Claude Code configuration (commands, hooks, skills)
- `codex/` — Codex CLI configuration (this file)

## Build & Test

```bash
# Install all workspace packages
uv sync --all-packages

# Run ALL tests from repo root
uv run pytest

# Run tests for a specific package
uv run pytest tasks/tests/
uv run pytest sandbox/tests/
uv run pytest ralph-cli/tests/
```

pytest uses `--import-mode=importlib` to avoid name collisions across packages.

## Code Conventions

- Python >= 3.10
- Formatter/linter: ruff (line-length 100)
- Build backend: hatchling
- Version: 0.0.1 (unified across monorepo)
- No `__init__.py` in test directories

## MCP Servers

- **md-task-mcp** — task management (projects, tasks, plans, reviews)

## Review Guidelines

### Severity Levels

- **CRITICAL** — security vulnerabilities, data loss, crashes
- **HIGH** — logic errors, missing validation, broken functionality
- **MEDIUM** — code quality, error handling gaps, missing edge cases
- **LOW** — style, naming, minor improvements

### Issue Format

```
### CRITICAL
1. **Issue Title** - path/to/file.py:42
   Description of the problem

### HIGH
1. **Issue Title** - path/to/file.py:100
   Description of the problem
```

### What to Check

1. **Correctness** — logic errors, edge cases, off-by-one, race conditions
2. **Security** — SQL injection, XSS, CSRF, hardcoded secrets, input validation
3. **Test coverage** — sufficient assertions, edge cases covered, no skipped tests
4. **Code quality** — naming, DRY, error handling, consistency with existing patterns
5. **Task compliance** — changes match the task requirements (get task via md-task-mcp)

### UI Verification (for frontend changes)

When changes touch `templates/`, `static/`, or UI-related code:

1. Start the dev server and navigate to the relevant pages
2. Verify UI renders correctly
3. Test forms with valid and invalid data
4. Include UI testing results in the review

### Review Output

Append results to the task's review field via md-task-mcp `update_task`.
Do NOT replace existing review content — always append.

If no issues found, write: `NO ISSUES FOUND`.
