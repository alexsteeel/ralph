# Changelog

## [Unreleased]

### Removed
- Cloud view template (`tasks/templates/tasks.html`) and tm CLI (`tasks/ralph_tasks/cli.py`) (#8)
  - Removed `tm` CLI (557 lines, click-based) — replaced by MCP server + direct API imports
  - Removed `/project/{name}` route (cloud view) from web.py
  - Removed view-toggle from kanban.html header
  - Removed `click>=8.1` dependency from ralph-tasks
  - Renamed entry point `tm-web` → `ralph-tasks-web`
  - `ralph-cli` now imports `ralph_tasks.core` directly (workspace dependency) instead of subprocess `tm`

### Added
- Neo4j graph database integration for ralph-tasks (#9)
  - Neo4j as shared Docker service in docker-compose (container `ai-sbx-neo4j`)
  - `GraphClient` wrapper with lazy driver init and managed transactions
  - Idempotent schema initialization (constraints, indexes, full-text indexes)
  - Full CRUD operations for 8 node types: Workspace, Project, Task, Section,
    Finding, Comment, WorkflowRun, WorkflowStep
  - Cascade delete for Task (removes sections, findings, comments, workflows)
  - Atomic auto-increment task numbering (TOCTOU-safe)
  - Cypher injection protection via `parent_label` whitelist and identifier validation
  - Comprehensive tests: 68 Neo4j tests (unit + integration), auto-skip when unavailable
- Final monorepo integration: Dockerfile, entrypoint, documentation (#7)
  - Dockerfile pip install URLs updated to monorepo (`ralph.git#subdirectory=...`)
  - entrypoint.sh MCP registration: `md-task-mcp` → `ralph-tasks`
  - `codex_config.toml` and `settings.example.json`: MCP server name updated
  - Root `conftest.py` for pytest discovery across all packages
  - `README.md` with setup, development, and architecture docs
  - `CLAUDE.md` transformed from migration plan to project instructions
  - Integration tests (32 tests) covering Dockerfile, entrypoint, hooks, CLI, MCP, docs
- Monorepo initialization with uv workspace (#1)
- Root `pyproject.toml` with workspace members: tasks, sandbox, ralph-cli
- Package skeletons: `ralph-tasks`, `ralph-sandbox`, `ralph-cli` (v0.0.1)
- Consolidated `.gitignore` from all source repos
- Codex CLI configuration: `codex/AGENTS.md` with project instructions for code review (#6)
- Empty config directories: `claude/{commands,hooks,skills}`
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
