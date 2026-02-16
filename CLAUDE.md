# Ralph Monorepo

AI development automation tools: task management, devcontainer management, autonomous task execution.

## Structure

```
ralph/
├── pyproject.toml              # uv workspace definition
├── uv.lock                     # Shared lock file
├── conftest.py                 # Root pytest discovery
├── tasks/                      # ralph-tasks package
│   ├── ralph_tasks/            # MCP server, CLI, web UI
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
| `ralph-tasks` | `tasks/` | `tm`, `tm-web`, `ralph-tasks serve` | Markdown task management + MCP server |
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
| `ralph_tasks` | `tm`, `tm-web` |
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
http://docker:<port>  # Any container port mapped with -p
```

Direct access to Docker bridge IPs (172.17.x.x) is blocked by tinyproxy. Always use `docker:<port>`.

### Docker

Packages are installed in devcontainers from the monorepo via git URLs:

```dockerfile
RUN uv pip install --system --break-system-packages --no-cache \
    "ralph-tasks @ git+https://github.com/alexsteeel/ralph.git#subdirectory=tasks"
RUN uv pip install --system --break-system-packages --no-cache \
    "ralph-cli @ git+https://github.com/alexsteeel/ralph.git#subdirectory=ralph-cli"
```

MCP server registration in `entrypoint.sh`:
```bash
claude mcp add -s user ralph-tasks -- ralph-tasks serve
```

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
