# Changelog

## [Unreleased]

### Added
- **ralph-cli, ralph-tasks: `--version` flag for CLI diagnostics** (#52)
  - `ralph --version` → `ralph-cli {version}` (typer callback with `is_eager=True`)
  - `ralph-tasks --version` → `ralph-tasks {version}` (sys.argv check in MCP entry point)
  - `ralph-tasks-web --version` → `ralph-tasks-web {version}` (sys.argv check in web entry point)
  - Version sourced from `importlib.metadata.version()` with `PackageNotFoundError` fallback to `"0.0.0"`
  - Tests: 7 new tests (CliRunner, subprocess, fallback with mock)

### Fixed
- **ralph-cli:** minor code quality issues (#67)
  - Removed duplicate `import re` from inside `_write()` method in `monitor.py` (moved to module level)
  - Standardized `check_lgtm()` error return from `(False, -1)` to `(False, None)` matching `_check_plan_lgtm()` pattern
  - Updated `recovery_delays` default from `[600, 1200, 1800]` to `[3600, 7200, 10800]` to match documentation
  - Improved `check_lgtm()` docstring to document `None` return on error

### Removed
- **ralph-cli:** dead code `create_branch()` and `switch_branch()` from `git.py` (#63)

### Added
- **claude: code-audit skill for automated codebase analysis** (#40)
  - New skill `claude/skills/code-audit.md` — automated codebase audit with task generation
  - 5 analysis categories: test coverage (pytest-cov + heuristic), dead code (ruff F4xx), code duplication, missing docstrings, CLAUDE.md pattern violations
  - Deduplication against existing tasks (done-tasks excluded, intra-run dedup)
  - Input validation for package, project, focus arguments
  - Safety section: prompt injection directives, consecutive failure escalation, hidden directory exclusion
  - Filterable by package (tasks, sandbox, ralph-cli, all) and focus category
- **ralph-cli: Codex plan review in `ralph plan`** (#25)
  - Automatic plan verification via Codex CLI after user approves plan in `ralph plan`
  - `run_codex_plan_review()` runs Codex as subprocess with stdout streaming and timeout handling
  - `_check_plan_lgtm()` queries Neo4j structured findings (review_type="plan") for open issues
  - `_build_codex_plan_prompt()` generates Codex prompt for MCP-based plan validation
  - New setting: `codex_plan_review_enabled` (default: True)
  - Graceful degradation: skips if Codex not in PATH or review disabled
  - 21 new tests in `test_plan_codex.py`, 124 total passing
- **ralph-cli: new implement pipeline with iterative review chain** (#16)
  - New `review_chain.py` module — orchestrates 5 review phases after main implementation
  - Phase pipeline: Code Review (4 parallel agents) → Simplifier → Security → Codex → Finalization
  - Iterative fix cycle: review → check LGTM via Neo4j findings → fix (resume session) → re-review
  - `check_lgtm()` queries Neo4j structured findings for open issues by section type
  - ThreadPoolExecutor-based parallel code reviews with thread-safe shared state
  - New `prompts.py` utility for loading `.md` prompt templates with variable substitution
  - 9 prompt files for review agents (code-reviewer, security-reviewer, codex-reviewer, etc.)
  - Prompt packaging via hatch force-include for wheel builds
  - New settings: `claude_review_model`, `code_review_max_iterations`, `security_review_max_iterations`
  - Updated `ralph-implement-python-task` skill: removed Phase 6 (Reviews), reviews now orchestrated externally
  - Removed old `ralph review` CLI command (replaced by review chain)
  - 54 new tests (49 review_chain + 5 prompts), 103 total passing
- **tasks: structured review findings — Section → Finding → Comment graph model** (#12)
  - Replaced plain-text `review` field with structured Neo4j-backed findings
  - New graph model: `Task -[:HAS_SECTION]→ Section -[:HAS_FINDING]→ Finding -[:HAS_COMMENT]→ Comment`
  - Finding fields: text, author, status (open/resolved/declined), file, line_start, line_end
  - Comment threads with replies via `REPLIED_BY` relationship
  - 5 new MCP tools: `add_review_finding`, `list_review_findings`, `reply_to_finding`, `resolve_finding`, `decline_finding`
  - Auto-creates review Section via MERGE on first finding
  - Validation: finding status enum, required decline reason, two-stage Cypher aggregation
  - Updated all review skills (ralph-review-code, security, simplify, codex-review) to use structured findings

### Fixed
- **sandbox: `ai-sbx init update` now regenerates both `.env` and `docker-compose.override.yaml`** (#27)
  - Previously `init update` only regenerated `.env`, leaving `docker-compose.override.yaml` with stale proxy settings
  - Re-running `init project` also updates derived files now (even with `force=False`)
  - New `_regenerate_derived_files()` helper ensures both files stay in sync
  - `.env` files now created with `0o600` permissions (owner-only read/write)
  - Guard added for missing `.devcontainer/` directory with user-friendly error

### Changed
- **sandbox: add --tag option to `image list` and `image verify` commands** (#26)
  - `ai-sbx image list --tag X` and `ai-sbx image verify --tag X` now check images with the specified tag instead of always using the default
  - Unified `--tag` help strings across `build`, `list`, and `verify` commands
  - Eliminated redundant double `_image_exists` call in `list_images` (halved subprocess invocations)
  - New tests: `test_list_images_with_custom_tag`, `test_list_images_default_tag`, `test_list_images_with_missing_and_custom_tag`, `test_verify_with_custom_tag`, `test_verify_default_tag`

### Added
- **tasks: security hardening — API auth, upload limits, port binding** (#37)
  - `ApiKeyMiddleware` ASGI middleware protecting `/api/*` and `/mcp/*` with `RALPH_TASKS_API_KEY` env var
  - Supports `Authorization: Bearer <key>` and `X-API-Key: <key>` headers (RFC 7235)
  - Timing-safe comparison via `hmac.compare_digest`, `WWW-Authenticate` header on 401
  - File upload size limit via `RALPH_TASKS_MAX_UPLOAD_MB` (default 50 MB), chunked read with Content-Length fast reject
  - Docker ports bound to `127.0.0.1` (MinIO, Neo4j, ralph-tasks, docker-registry-proxy)
  - `migrate_project_prefix()` validates sanitized components (prevents empty prefix)
  - MCP registration with `--header "Authorization: Bearer ..."` when API key is set
  - Stdio fallback skipped when API key is configured (auth bypass prevention)
  - JavaScript `authHeaders()` helper in templates for authenticated fetch calls
  - New tests: 16 auth/upload tests in `test_web_mcp_mount.py`, 6 sanitization tests in `test_storage.py`
- **tasks: project name normalization — hyphens vs underscores** (#36)
  - `normalize_project_name()` in `core.py` — canonical form uses hyphens (`face_recognition` → `face-recognition`)
  - Applied to all 14 public functions in `core.py` (projects, tasks, attachments)
  - Auto-migration at startup: renames existing underscore projects to canonical form
  - `rename_project()` in `graph/crud.py` for Neo4j project renaming
  - `migrate_project_prefix()` in `storage.py` for MinIO object key migration
  - 301 redirect in `/kanban/{name}` for non-canonical URLs (preserves query params)
  - Normalized project name in `create_project` web API response
  - Consistent cache paths in MCP `read_attachment`
  - New tests: 7 unit tests for `normalize_project_name`, 8 Neo4j integration tests, 3 migration tests, 3 web redirect tests
- **tasks: containerize ralph-tasks MCP server** (#33)
  - Combined ASGI app: FastAPI web UI + FastMCP streamable-http on single port 8000
  - `get_mcp_http_app()` in `mcp.py` — returns Starlette app mounted at `/mcp`
  - `/health` endpoint for Docker HEALTHCHECK
  - `main()` reads `RALPH_TASKS_HOST`/`RALPH_TASKS_PORT` from environment
  - New `tasks/Dockerfile`: python:3.12-slim, non-root user, uv install
  - `ralph-tasks` service in docker-compose (`ai-sbx-ralph-tasks`, port 8000)
  - Entrypoint MCP registration: streamable-http with health check, stdio fallback
  - Container tracking in `init.py`
  - New tests: `test_web_mcp_mount.py` (11 tests)
- **tasks: MinIO S3 attachment storage** (#35)
  - New `ralph_tasks/storage.py` — S3 storage module with lazy-singleton MinIO client
  - Object keys: `{project}/{NNN}/{filename}` with input sanitization (`_sanitize_key_component`)
  - Public API: `put_bytes`, `get_object`, `list_objects`, `delete_object`, `delete_all_objects`, `object_exists`, `get_presigned_url`
  - New MCP tool `read_attachment` — downloads from MinIO to temp path for Claude's Read tool
  - Web download endpoint uses `StreamingResponse` instead of `FileResponse`
  - Content-Disposition header injection protection (escaping quotes/backslashes)
  - MinIO dev service in docker-compose (`ai-sbx-minio`, ports 9000/9001)
  - MinIO test service in `tasks/tests/docker-compose.yaml` (port 19000, tmpfs)
  - `@pytest.mark.minio` with auto-skip when MinIO unavailable (pattern matches Neo4j)
  - New tests: `test_storage.py` (18 tests), `test_attachments.py` (13 tests)
  - Dependency: `minio>=7.0`

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
