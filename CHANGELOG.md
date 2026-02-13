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
- `.claude/{commands,hooks,skills}` → `claude/` config directory (#4)
  - 14 command definitions (`claude/commands/*.md`)
  - 5 workflow hooks (`claude/hooks/`: check_workflow, check_workflow_ralph, enforce_isolated_skills, hook_utils, notify)
  - 1 skill (`claude/skills/task-manager.md`)
  - 1 settings template (`claude/settings.example.json`)
  - Fixed hardcoded paths: `check_workflow.py` (`Path.home()`), `notify.sh` (`$HOME`)
  - Ruff linter fixes: unused f-string prefix, duplicate import, import order
- `md-task-mcp` → `tasks/` as `ralph-tasks` package (#2)
  - Core data layer (`ralph_tasks/core.py`)
  - MCP server (`ralph_tasks/mcp.py`, renamed from `main.py`)
  - CLI (`ralph_tasks/cli.py`, entry points: `tm`, `tm-web`)
  - Web UI (`ralph_tasks/web.py`, FastAPI + Jinja2)
  - Templates (`tasks/templates/`), skill (`tasks/skills/task-manager.md`)
  - Tests (`tasks/tests/test_core.py`, 32 tests passing)
  - Runtime compatibility preserved: `~/.md-task-mcp` data path, logger name
- `ai-agents-sandbox` → `sandbox/` as `ralph-sandbox` package (#3)
  - CLI (`ralph_sandbox/cli.py`, entry point: `ai-sbx`)
  - Configuration (`ralph_sandbox/config.py`, Pydantic v2 models)
  - Commands: init, image, worktree, docker, doctor, notify, upgrade
  - Templates manager (`ralph_sandbox/templates.py`)
  - Utilities (`ralph_sandbox/utils.py`)
  - Dockerfiles (10 variants), resources, templates
  - Tests (78 total: 68 existing + 10 migration-specific)
  - All `ai_sbx` imports renamed to `ralph_sandbox`
  - Runtime strings preserved (`ai-sbx` CLI, `.ai-sbx` config dir)
  - Ruff linter fixes applied (76 auto-fixed style issues)
- `.claude/cli/` → `ralph-cli/` as `ralph-cli` package (#5)
  - Package renamed: `ralph` → `ralph_cli` (17 modules, 7 test files)
  - CLI entry point: `ralph = "ralph_cli.cli:main"`
  - Commands: implement, plan, interview, review, health, logs, notify
  - Error classification, executor, git ops, recovery loop, stream monitor
  - Tests: 82 passing (imports updated, test_package adapted)
  - Dependencies: typer, pydantic-settings, gitpython>=3.1.41 (CVE fix), rich
  - Ruff linter fixes applied (101 auto-fixed), B008 excluded for Typer pattern
  - All internal imports are relative (no changes needed for rename)
