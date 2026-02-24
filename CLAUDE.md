# Ralph Monorepo

AI development automation tools: task management, devcontainer management, autonomous task execution.

## Structure

```
ralph/
├── pyproject.toml              # uv workspace definition
├── uv.lock                     # Shared lock file
├── conftest.py                 # Root pytest discovery
├── tasks/                      # ralph-tasks package
│   ├── ralph_tasks/            # MCP server, web UI
│   ├── templates/              # Jinja2 templates
│   └── tests/
├── sandbox/                    # ralph-sandbox package
│   ├── ralph_sandbox/          # CLI, config, commands, dockerfiles
│   └── tests/
├── ralph-cli/                  # ralph-cli package
│   ├── ralph_cli/              # CLI, executor, recovery
│   └── tests/
├── claude/                     # Claude Code configuration
│   ├── commands/               # Slash commands (.md)
│   ├── hooks/                  # Workflow hooks (.py, .sh)
│   └── skills/                 # Claude skills (.md)
└── codex/                      # Codex CLI configuration
    └── AGENTS.md
```

## Packages

| Package | Directory | CLI Commands | Description |
|---------|-----------|--------------|-------------|
| `ralph-tasks` | `tasks/` | `ralph-tasks serve`, `ralph-tasks-web` | Neo4j-backed task management + MCP server |
| `ralph-sandbox` | `sandbox/` | `ai-sbx` | Devcontainer management for AI agents |
| `ralph-cli` | `ralph-cli/` | `ralph` | Autonomous task execution with API recovery |

## Architecture Decisions

### AD-1: uv workspace

Single workspace, shared lockfile. Internal dependency: `ralph-cli` depends on `ralph-tasks` (via workspace).

### AD-2: Flat layout

No `src/` directory: `tasks/ralph_tasks/`, `sandbox/ralph_sandbox/`, `ralph-cli/ralph_cli/`.

### AD-3: Package names

| Package Import | CLI Command |
|---------------|-------------|
| `ralph_tasks` | `ralph-tasks-web` |
| `ralph_sandbox` | `ai-sbx` |
| `ralph_cli` | `ralph` |

### AD-4: claude/ as deployment artifact

`claude/` is a template for `~/.claude/` in devcontainers. Dockerfile copies it into the container.

### AD-5: Per-package tests

```bash
uv run pytest                    # All tests
uv run pytest tasks/tests/       # ralph-tasks only
uv run pytest sandbox/tests/     # ralph-sandbox only
uv run pytest ralph-cli/tests/   # ralph-cli only
```

## Development

### Setup

```bash
uv sync --all-packages
```

### Testing

```bash
uv run pytest
```

Uses `--import-mode=importlib` to avoid name collisions between test files across packages. Do NOT add `__init__.py` to test directories.

### Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

### Devcontainer networking

Devcontainer uses Docker-in-Docker (DinD). The DinD service is named `docker` in docker-compose. Containers started via `docker run` inside devcontainer run inside DinD. Their mapped ports are accessible from devcontainer by hostname `docker`.

Shared infrastructure services (Neo4j, MinIO, PostgreSQL, ralph-tasks) run on the host Docker in the `ai-sbx-proxy-internal` network. Devcontainer is also connected to this network and reaches them by container name:

```
bolt://ai-sbx-neo4j:7687       # Neo4j Bolt
http://ai-sbx-neo4j:7474       # Neo4j HTTP
http://ai-sbx-minio:9000       # MinIO S3 API (internal port)
http://ai-sbx-minio:9001       # MinIO Console (internal port)
postgresql://ai-sbx-postgres:5432  # PostgreSQL
http://ai-sbx-ralph-tasks:8000 # ralph-tasks web UI + MCP
docker:<port>                   # DinD mapped ports (containers started inside devcontainer)
```

Direct access to Docker bridge IPs (172.17.x.x) is blocked by tinyproxy. Use container names for shared infra, `docker:<port>` for DinD.

### Docker

Packages are installed in devcontainers via local COPY from the monorepo root (build context):

```dockerfile
COPY tasks/ /tmp/ralph-tasks/
RUN uv pip install --system --break-system-packages --no-cache /tmp/ralph-tasks/ \
    && rm -rf /tmp/ralph-tasks/

COPY ralph-cli/ /tmp/ralph-cli/
RUN uv pip install --system --break-system-packages --no-cache /tmp/ralph-cli/ \
    && rm -rf /tmp/ralph-cli/
```

The `ai-sbx image build` command uses the monorepo root as Docker build context, found via `uv.lock` + `tasks/` + `sandbox/` markers.

### ralph-tasks container

The ralph-tasks MCP server runs as a shared Docker container (`ai-sbx-ralph-tasks`) serving both the Kanban web UI and MCP endpoint on port 8000:

- `http://ai-sbx-ralph-tasks:8000/` — Kanban web UI (from devcontainer via `ai-sbx-proxy-internal` network)
- `http://ai-sbx-ralph-tasks:8000/mcp-swe` — SWE role MCP endpoint (streamable-http)
- `http://ai-sbx-ralph-tasks:8000/mcp-review?review_type=<type>` — Reviewer role MCP endpoint
- `http://ai-sbx-ralph-tasks:8000/mcp-plan` — Planner role MCP endpoint
- `http://ai-sbx-ralph-tasks:8000/dashboard` — Metrics dashboard
- `http://ai-sbx-ralph-tasks:8000/health` — Docker HEALTHCHECK
- `http://localhost:58000/` — Kanban web UI (from host, via port mapping)
- `http://localhost:58000/dashboard` — Metrics dashboard (from host, via port mapping)

Build: `docker build -f tasks/Dockerfile .` (from monorepo root).

MCP server registration in `entrypoint.sh` (HTTP-only, no stdio fallback):
```bash
# Devcontainer reaches ralph-tasks via ai-sbx-proxy-internal network
# Uses /mcp-swe endpoint (SWE role with full developer access)
if curl -sf --max-time 3 "http://ai-sbx-ralph-tasks:8000/health" >/dev/null 2>&1; then
    claude mcp add -s user --transport http [--header "Authorization: Bearer $KEY"] ralph-tasks "http://ai-sbx-ralph-tasks:8000/mcp-swe"
fi
```

Environment variables for ralph-tasks container:
- `NEO4J_URI` — Neo4j Bolt URI (default: `bolt://ai-sbx-neo4j:7687`)
- `NEO4J_USER` / `NEO4J_PASSWORD` — Neo4j credentials
- `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — MinIO credentials
- `RALPH_TASKS_HOST` / `RALPH_TASKS_PORT` — bind address (default: `127.0.0.1:8000`)
- `RALPH_TASKS_API_KEY` — API key for `/api/*` and `/mcp-*` authentication (empty = disabled)
- `RALPH_TASKS_MAX_UPLOAD_MB` — maximum upload size in MB (default: `50`)
- `POSTGRES_URI` — PostgreSQL connection URI (default: `postgresql://ralph:ralph-ai-sbx-password@ai-sbx-postgres:5432/ralph`)

## Development Notes

### uv workspace: installing workspace members

`uv sync` (without flags) installs only root dev-dependencies.
To install all workspace packages: `uv sync --all-packages`.
For running tests: `uv run pytest` — automatically installs needed packages.

### uv workspace: internal dependencies

When one workspace member depends on another, add `[tool.uv.sources]` in its `pyproject.toml`:
```toml
[tool.uv.sources]
ralph-tasks = { workspace = true }
```

### pytest: monorepo test collection

Use `--import-mode=importlib` in pytest config to avoid name collisions between `test_package.py` files in different packages. Do NOT use `__init__.py` in test directories.

### typer: `[all]` extra removed

`typer[all]>=0.9` produces a warning — the `all` extra was removed. Use `typer>=0.9` instead.

### dependency-groups (PEP 735)

`[tool.uv] dev-dependencies` is deprecated. Use `[dependency-groups] dev = [...]` instead.

### Neo4j tests: auto-skip when unavailable

Neo4j tests use `@pytest.mark.neo4j` marker and auto-skip when the database is unreachable. The test conftest tries `bolt://ai-sbx-neo4j:7687` first (devcontainer via proxy-internal network), then `bolt://docker:7687`, then `bolt://localhost:7687`. Override via `NEO4J_TEST_URI` env var. Test credentials: `NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` (defaults: `neo4j`/`testpassword123`).

### MinIO attachment storage

Task attachments are stored in MinIO (S3-compatible object storage). Configuration via environment variables:
- `MINIO_ENDPOINT` (default: `localhost:9000`, devcontainer: `ai-sbx-minio:9000`)
- `MINIO_ACCESS_KEY` (default: `minioadmin`)
- `MINIO_SECRET_KEY` (default: `minioadmin`)
- `MINIO_BUCKET` (default: `ralph-tasks`)
- `MINIO_SECURE` (default: `false`)

Object keys follow the pattern `{project}/{NNN}/{filename}`. The storage module (`ralph_tasks/storage.py`) uses a lazy-singleton pattern matching `graph/client.py`.

### PostgreSQL metrics storage

Session and task execution metrics are stored in PostgreSQL. The metrics module (`ralph_tasks/metrics/database.py`) uses a lazy-singleton `ThreadedConnectionPool` pattern matching `storage.py` and `graph/client.py`. Schema is created automatically via `ensure_schema()` on server startup (`CREATE TABLE IF NOT EXISTS`).

Tables: `sessions` (command_type, project, model, cost, tokens, timestamps, exit_code) and `task_executions` (per-task metrics linked to session via FK with CASCADE delete).

API endpoints (`/api/metrics/*`) provide summary, timeline, and breakdown aggregations for the dashboard. Protected by `ApiKeyMiddleware`. The `/dashboard` route serves the Chart.js-based UI (no auth required — fetches data via client-side JS with API key).

ralph-cli sends metrics via fire-and-forget HTTP POST (`ralph_cli/metrics.py`, stdlib `urllib` only). If ralph-tasks is unavailable, a warning is logged and the workflow continues. If not configured (`ralph_tasks_api_url` is unset), submission is silently skipped.

Configuration:
- `POSTGRES_URI` — connection string (default: `postgresql://ralph:ralph@localhost:5432/ralph`, devcontainer: `postgresql://ralph:ralph-ai-sbx-password@ai-sbx-postgres:5432/ralph`)
- `RALPH_TASKS_API_URL` — ralph-tasks base URL for CLI metric submission (ralph-cli config, env: `RALPH_TASKS_API_URL`)
- `RALPH_TASKS_API_KEY` — API key for authentication (ralph-cli config, env: `RALPH_TASKS_API_KEY`)

### MinIO tests: auto-skip when unavailable

MinIO tests use `@pytest.mark.minio` marker and auto-skip when MinIO is unreachable. The test conftest tries `ai-sbx-minio:9000` first (devcontainer via proxy-internal network), then `docker:59000`, then `localhost:59000`, then `localhost:19000` (test docker-compose). Override via `MINIO_TEST_ENDPOINT` env var. Test credentials: `MINIO_TEST_ACCESS_KEY`/`MINIO_TEST_SECRET_KEY` (defaults: `minioadmin`/`minioadmin`).

### PostgreSQL tests: auto-skip when unavailable

PostgreSQL tests use `@pytest.mark.postgres` marker and auto-skip when the database is unreachable. The test conftest tries `ai-sbx-postgres:5432` first (devcontainer via proxy-internal network), then `docker:55432`, then `localhost:55432`, then `localhost:15432` (test docker-compose). Override via `POSTGRES_TEST_URI` env var. Test database/user: `ralph_test`/`ralph_test` (not the production `ralph`/`ralph`). Test credentials default password: `testpassword123`.

The `pg_database` fixture (per-test scope) sets `POSTGRES_URI` env var via monkeypatch, calls `ensure_schema()`, and truncates tables on teardown.

### Neo4j credentials: NEO4J_AUTH vs NEO4J_USER/NEO4J_PASSWORD

Neo4j Docker image uses `NEO4J_AUTH=neo4j/password` (slash-separated) format. The Python Neo4j driver (`GraphClient`) expects **separate** `NEO4J_USER` and `NEO4J_PASSWORD` variables. When configuring docker-compose services:

```yaml
# Neo4j container (image format):
NEO4J_AUTH: neo4j/testpassword123

# ralph-tasks app container (driver format):
NEO4J_USER: neo4j
NEO4J_PASSWORD: testpassword123
```

Do NOT pass `NEO4J_AUTH` to ralph-tasks — it won't be parsed correctly.

### PostgreSQL credentials: POSTGRES_URI

PostgreSQL uses a single `POSTGRES_URI` connection string for the application. The Docker image expects separate `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` environment variables.

```yaml
# PostgreSQL container (image format):
POSTGRES_USER: ralph
POSTGRES_PASSWORD: ralph-ai-sbx-password
POSTGRES_DB: ralph

# ralph-tasks app container (URI format):
POSTGRES_URI: postgresql://ralph:ralph-ai-sbx-password@ai-sbx-postgres:5432/ralph
```

### ralph-cli config: metrics submission

ralph-cli uses settings from `~/.claude/.env` or environment variables to submit metrics to ralph-tasks:

- `ralph_tasks_api_url` (env: `RALPH_TASKS_API_URL`) — ralph-tasks base URL (e.g., `http://ai-sbx-ralph-tasks:8000`)
- `ralph_tasks_api_key` (env: `RALPH_TASKS_API_KEY`) — API key for `/api/*` endpoints

If `ralph_tasks_api_url` is not set, metrics submission is silently skipped. The submission uses stdlib `urllib` (no external dependencies) with a 10-second timeout and never raises exceptions.
