# Changelog

## [Unreleased]

### Added
- Monorepo initialization with uv workspace (#1)
- Root `pyproject.toml` with workspace members: tasks, sandbox, ralph-cli
- Package skeletons: `ralph-tasks`, `ralph-sandbox`, `ralph-cli` (v0.0.1)
- Consolidated `.gitignore` from all source repos
- Empty config directories: `claude/{commands,hooks,skills}`, `codex/`
- Workspace tests verifying structure, imports, and version consistency
- Per-package smoke tests

### Migrated
- `md-task-mcp` → `tasks/` as `ralph-tasks` package (#2)
  - Core data layer (`ralph_tasks/core.py`)
  - MCP server (`ralph_tasks/mcp.py`, renamed from `main.py`)
  - CLI (`ralph_tasks/cli.py`, entry points: `tm`, `tm-web`)
  - Web UI (`ralph_tasks/web.py`, FastAPI + Jinja2)
  - Templates (`tasks/templates/`), skill (`tasks/skills/task-manager.md`)
  - Tests (`tasks/tests/test_core.py`, 32 tests passing)
  - Runtime compatibility preserved: `~/.md-task-mcp` data path, logger name
