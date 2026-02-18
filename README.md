# Ralph

Monorepo for AI development automation tools.

## Packages

| Package | Directory | CLI Command | Description |
|---------|-----------|-------------|-------------|
| `ralph-tasks` | `tasks/` | `ralph-tasks` (MCP), `ralph-tasks-web` | Markdown-based task management |
| `ralph-sandbox` | `sandbox/` | `ai-sbx` | Devcontainer management for AI agents |
| `ralph-cli` | `ralph-cli/` | `ralph` | Autonomous task execution with API recovery |

## Configuration

| Directory | Description |
|-----------|-------------|
| `claude/` | Claude Code hooks, commands, skills |
| `codex/` | Codex CLI configuration |

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python package manager).

```bash
# Install all workspace packages
uv sync --all-packages

# Install dev dependencies only
uv sync
```

## Development

### Running Tests

```bash
# All tests from root
uv run pytest

# Tests for a specific package
uv run pytest tasks/tests/
uv run pytest sandbox/tests/
uv run pytest ralph-cli/tests/
```

### Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

### CLI Commands

```bash
# Task management web UI
uv run ralph-tasks-web

# Devcontainer management
uv run ai-sbx --help

# Autonomous task execution
uv run ralph --help
```

### MCP Server

```bash
# Start ralph-tasks MCP server (stdio mode)
uv run ralph-tasks serve
```

## Architecture

- **uv workspace** — single lockfile, shared dev dependencies
- **Flat layout** — `tasks/ralph_tasks/`, not `tasks/src/ralph_tasks/`
- **Per-package tests** — each package has its own `tests/` directory
- **`--import-mode=importlib`** — avoids name collisions in monorepo test collection
- **Target architecture (graph-first)** — `docs/target-architecture.md`

## Docker

Packages are installed in devcontainers via local COPY from the monorepo root (build context):

```dockerfile
COPY tasks/ /tmp/ralph-tasks/
RUN uv pip install --system --break-system-packages --no-cache /tmp/ralph-tasks/ \
    && rm -rf /tmp/ralph-tasks/

COPY ralph-cli/ /tmp/ralph-cli/
RUN uv pip install --system --break-system-packages --no-cache /tmp/ralph-cli/ \
    && rm -rf /tmp/ralph-cli/
```
