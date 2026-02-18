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

Devcontainer uses Docker-in-Docker (DinD). The DinD service is named `docker` in docker-compose. Containers started via `docker run` inside devcontainer run inside DinD. Their mapped ports are accessible from devcontainer by hostname `docker`:

```
bolt://docker:7687    # Neo4j Bolt
http://docker:7474    # Neo4j HTTP
http://docker:9000    # MinIO S3 API
http://docker:9001    # MinIO Console
http://docker:<port>  # Any container port mapped with -p
```

Direct access to Docker bridge IPs (172.17.x.x) is blocked by tinyproxy. Always use `docker:<port>`.

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

- `http://docker:8000/` — Kanban web UI (from devcontainer, via DinD mapped port)
- `http://docker:8000/mcp` — MCP endpoint (streamable-http)
- `http://docker:8000/health` — Docker HEALTHCHECK

Build: `docker build -f tasks/Dockerfile .` (from monorepo root).

MCP server registration in `entrypoint.sh` (with health check fallback):
```bash
# Prefer streamable-http if container is running, fallback to local stdio
# Use 'docker' hostname (DinD mapped ports) — container names are not resolvable from devcontainer
if curl -sf --max-time 3 "http://docker:8000/health" >/dev/null 2>&1; then
    claude mcp add -s user --transport http ralph-tasks "http://docker:8000/mcp"
else
    claude mcp add -s user ralph-tasks -- ralph-tasks serve
fi
```

Environment variables for ralph-tasks container:
- `NEO4J_URI` — Neo4j Bolt URI (default: `bolt://ai-sbx-neo4j:7687`)
- `NEO4J_USER` / `NEO4J_PASSWORD` — Neo4j credentials
- `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` — MinIO credentials
- `RALPH_TASKS_HOST` / `RALPH_TASKS_PORT` — bind address (default: `127.0.0.1:8000`)

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

Neo4j tests use `@pytest.mark.neo4j` marker and auto-skip when the database is unreachable. The test conftest tries `bolt://docker:7687` first (devcontainer DinD), then `bolt://localhost:7687`. Override via `NEO4J_TEST_URI` env var. Test credentials: `NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` (defaults: `neo4j`/`testpassword123`).

### MinIO attachment storage

Task attachments are stored in MinIO (S3-compatible object storage). Configuration via environment variables:
- `MINIO_ENDPOINT` (default: `localhost:9000`, devcontainer: `docker:9000`)
- `MINIO_ACCESS_KEY` (default: `minioadmin`)
- `MINIO_SECRET_KEY` (default: `minioadmin`)
- `MINIO_BUCKET` (default: `ralph-tasks`)
- `MINIO_SECURE` (default: `false`)

Object keys follow the pattern `{project}/{NNN}/{filename}`. The storage module (`ralph_tasks/storage.py`) uses a lazy-singleton pattern matching `graph/client.py`.

### MinIO tests: auto-skip when unavailable

MinIO tests use `@pytest.mark.minio` marker and auto-skip when MinIO is unreachable. The test conftest tries `docker:9000` first (devcontainer DinD), then `localhost:9000`, then `localhost:19000` (test docker-compose). Override via `MINIO_TEST_ENDPOINT` env var. Test credentials: `MINIO_TEST_ACCESS_KEY`/`MINIO_TEST_SECRET_KEY` (defaults: `minioadmin`/`minioadmin`).

### `ralph review` inside nested Claude Code sessions

`ralph review` CLI cannot run inside another Claude Code session (nested sessions crash). Use Task agents with `subagent_type="pr-review-toolkit:code-reviewer"` etc. as a workaround when running reviews from within Claude Code.

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
