# Changelog

## [Unreleased]

### Changed
- **sandbox: Docker build from monorepo root instead of git+https** (#23)
  - Replaced `git+https://github.com/...` package installation in devcontainer Dockerfile with local `COPY + pip install` from monorepo
  - Changed Docker build context from `dockerfiles/` to monorepo root via `_find_monorepo_root()`
  - Updated all COPY paths in Dockerfiles (devcontainer-base, tinyproxy, tinyproxy-registry, docker-dind) to use `sandbox/ralph_sandbox/dockerfiles/` prefix
  - Added `_is_ralph_monorepo()` validation (checks `uv.lock` + `tasks/` + `sandbox/` dirs)
  - Added `.dockerignore` at monorepo root to minimize build context
  - Updated CLAUDE.md Docker section to reflect new approach
  - New tests: `TestFindMonorepoRoot` (5 tests), `TestBuildImageSignature` (2 tests), `TestBuildCommandMonorepoRoot` (1 test)

### Removed
- **ralph-cli: unused CLI parameters and config settings** (#32)
  - Removed `--max-budget` from `ralph implement` CLI and entire call chain (cli.py → implement.py → executor.py)
  - Removed `--no-recovery` from `ralph implement` CLI and implement.py (recovery can still be disabled via `RECOVERY_ENABLED=false` in `.env`)
  - Removed `cli_dir` from Settings (unused path)
  - Removed `codex_review_fix_timeout` from Settings (unused timeout)
  - Updated tests: `test_config.py`, `test_implement_codex.py`
- **sandbox: C#/.NET and Go dockerfiles removed** (#20)
  - Deleted `devcontainer-dotnet/` (C#/.NET SDK Dockerfile) and `devcontainer-golang/` (Go toolchain Dockerfile)
  - Removed `DOTNET`, `GOLANG` from `BaseImage` enum — only `BASE` remains
  - Simplified `get_docker_image_name()`, `_get_environment_image_spec()` — direct returns instead of mappings
  - Removed dotnet/golang from wizard choices, CLI options, build order, image lists
  - Removed `OPTIONAL_IMAGES` list (was empty after cleanup)
  - Removed redundant `None`-checks and dead code paths across docker.py, init.py, cli.py

### Changed
- **core.py rewritten: file storage → Neo4j graph database** (#10)
  - All task/project CRUD operations now use Neo4j via `graph/crud.py`
  - New clean public API: `create_task()`, `get_task()`, `update_task()`, `list_tasks()`
  - Removed file-based functions: `read_task()`, `write_task()`, `parse_task_file()`, `task_to_string()`
  - Task dataclass: removed `file_path`/`mtime`, added `updated_at` (ISO 8601)
  - Auto-timestamps in core: `started` on status→work, `completed` on status→done/approved
  - Attachments remain file-based at `~/.md-task-mcp/<project>/attachments/<NNN>/`
  - Path traversal protection: `_safe_name()` for project names, `Path(filename).name` for filenames
  - mcp.py simplified: thin delegation to core API
  - web.py simplified: removed backup functionality, uses core API directly
  - Old file-based core preserved as `core_file.py` for migration task (#11)
  - New tests: `test_core_neo4j.py` (34 tests), `test_core_file.py` (5 tests)
  - Extended `graph/crud.py` with `get_task_full()`, `upsert_section()`, `sync_dependencies()`

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
