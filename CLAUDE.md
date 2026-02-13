# Ralph Monorepo — Migration Plan

## Context

Объединение 4 тесно связанных репозиториев в один монорепо:

| Source Repo | Target Dir | Package Name | CLI Command |
|-------------|-----------|--------------|-------------|
| `md-task-mcp` | `tasks/` | `ralph-tasks` | `tm`, `tm-web`, `ralph-tasks` (MCP) |
| `ai-agents-sandbox` | `sandbox/` | `ralph-sandbox` | `ai-sbx` |
| `.claude/cli/` | `ralph-cli/` | `ralph-cli` | `ralph` |
| `.claude/{hooks,commands,skills}` | `claude/` | — (не пакет, конфигурация) | — |
| codex config | `codex/` | — (не пакет, конфигурация) | — |

## Target Structure

```
ralph/                              # Root monorepo
├── pyproject.toml                  # uv workspace definition
├── uv.lock                         # Shared lock file
├── CLAUDE.md                       # Project instructions
├── README.md
├── .gitignore
│
├── tasks/                          # md-task-mcp → ralph-tasks
│   ├── pyproject.toml              # Package: ralph-tasks
│   ├── ralph_tasks/                # Python package (flat layout)
│   │   ├── __init__.py
│   │   ├── core.py                 # Task/project data layer
│   │   ├── mcp.py                  # MCP server (was main.py)
│   │   ├── cli.py                  # CLI: tm, tm-web
│   │   └── web.py                  # FastAPI web UI
│   ├── templates/                  # Jinja2 templates
│   │   ├── base.html
│   │   ├── kanban.html
│   │   ├── projects.html
│   │   └── tasks.html
│   ├── skills/
│   │   └── task-manager.md         # Claude skill for MCP
│   └── tests/
│       └── test_core.py
│
├── sandbox/                        # ai-agents-sandbox → ralph-sandbox
│   ├── pyproject.toml              # Package: ralph-sandbox
│   ├── ralph_sandbox/              # Python package (flat layout)
│   │   ├── __init__.py
│   │   ├── cli.py                  # Main CLI entry (Click)
│   │   ├── config.py               # Pydantic models
│   │   ├── templates.py            # Jinja2 template mgmt
│   │   ├── utils.py                # Utilities
│   │   ├── commands/               # CLI subcommands
│   │   │   ├── docker.py
│   │   │   ├── doctor.py
│   │   │   ├── image.py
│   │   │   ├── init.py
│   │   │   ├── notify.py
│   │   │   ├── upgrade.py
│   │   │   └── worktree/
│   │   ├── dockerfiles/            # Docker images
│   │   ├── resources/              # Docker proxy etc.
│   │   └── templates/              # .devcontainer templates
│   ├── docs/
│   │   └── ARCHITECTURE.md
│   └── tests/
│       ├── test_cli.py
│       ├── test_config.py
│       ├── test_image_commands.py
│       ├── test_templates.py
│       └── test_utils.py
│
├── ralph-cli/                      # .claude/cli → ralph-cli
│   ├── pyproject.toml              # Package: ralph-cli
│   ├── ralph_cli/                  # Python package (flat layout)
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cli.py                  # Typer CLI definition
│   │   ├── config.py               # Pydantic settings
│   │   ├── errors.py               # Error classification
│   │   ├── executor.py             # Claude process execution
│   │   ├── git.py                  # Git operations
│   │   ├── health.py               # API health checks
│   │   ├── logging.py              # Rich logging
│   │   ├── monitor.py              # Stream JSON monitoring
│   │   ├── notify.py               # Telegram notifications
│   │   ├── recovery.py             # Recovery loop
│   │   └── commands/
│   │       ├── health.py
│   │       ├── implement.py
│   │       ├── interview.py
│   │       ├── logs.py
│   │       ├── notify.py
│   │       ├── plan.py
│   │       └── review.py
│   └── tests/
│       ├── conftest.py
│       ├── test_config.py
│       ├── test_errors.py
│       ├── test_executor.py
│       ├── test_git.py
│       ├── test_implement_codex.py
│       └── test_logs.py
│
├── claude/                         # Claude Code configuration
│   ├── commands/                   # Slash commands (.md)
│   ├── hooks/                      # Workflow hooks
│   ├── skills/                     # Claude skills
│   └── settings.json               # Claude settings
│
└── codex/                          # Codex CLI configuration
    ├── AGENTS.md                   # Codex agents config
    └── ...
```

## Architecture Decisions

### AD-1: uv workspace (Python monorepo)

Root `pyproject.toml`:
```toml
[project]
name = "ralph"
version = "0.0.1"

[tool.uv.workspace]
members = ["tasks", "sandbox", "ralph-cli"]

[tool.uv]
dev-dependencies = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.4",
]
```

Каждый пакет имеет свой `pyproject.toml` с зависимостями. Внутренние зависимости:
- `ralph-cli` → зависит от `ralph-tasks` (через workspace)
- `sandbox` и `tasks` — независимы друг от друга

### AD-2: Flat layout (без src/)

Пакеты размещаются без промежуточной `src/` директории:
- `tasks/ralph_tasks/` — не `tasks/src/ralph_tasks/`
- `sandbox/ralph_sandbox/` — не `sandbox/src/ralph_sandbox/`
- `ralph-cli/ralph_cli/` — не `ralph-cli/src/ralph_cli/`

### AD-3: Переименование пакетов

| Old Import | New Import | CLI Command |
|-----------|-----------|-------------|
| `from ralph.cli import ...` | `from ralph_cli.cli import ...` | `ralph` (без изменений) |
| `from ai_sbx.cli import ...` | `from ralph_sandbox.cli import ...` | `ai-sbx` (без изменений) |
| `import core` (md-task-mcp) | `from ralph_tasks.core import ...` | `tm` (без изменений) |

CLI-команды остаются прежними для обратной совместимости.

### AD-4: claude/ как деплоймент-артефакт

Директория `claude/` — это **шаблон** для `~/.claude/` в контейнере. При установке sandbox:
1. Dockerfile копирует `claude/` → `~/.claude/`
2. Или: symlink `~/.claude/commands` → `/workspace/claude/commands`

### AD-5: Тесты per-package

```bash
# Запуск всех тестов из корня
uv run pytest

# Запуск тестов конкретного пакета
uv run pytest tasks/tests/
uv run pytest sandbox/tests/
uv run pytest ralph-cli/tests/
```

### AD-6: Миграция через copy + минимальные доработки

Принцип: **копировать файлы, менять только структуру и импорты**.
- `cp` исходных файлов → целевые директории
- Обновить импорты (имя пакета)
- Обновить pyproject.toml (entry points, dependencies)
- НЕ рефакторить логику, НЕ менять API, НЕ оптимизировать

## Decisions Made

- **CLI:** 3 отдельных CLI (ralph, ai-sbx, tm) — оставить как есть. Объединение — отдельная задача.
- **Packaging:** uv workspace, отдельные пакеты, flat layout (без src/)
- **Versioning:** единая версия монорепо, начать с 0.0.1
- **CI/CD:** отдельная задача после миграции
- **Tests:** per-package, `uv run pytest` собирает все из корня
- **Migration:** copy-first, минимальные изменения (структура + импорты)

## Open Questions

- [ ] Как sandbox устанавливает пакеты из монорепо в Docker? (pip install "ralph-tasks @ git+...#subdirectory=tasks")
- [ ] Нужно ли сохранять git history из старых репозиториев? (git subtree / filter-repo)

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

## Source Repos Location

```
/media/bas/data/repo/github/
├── ai-agents-sandbox/          # → sandbox/
├── md-task-mcp/                # → tasks/
├── .claude/                    # → claude/ + ralph-cli/
│   ├── cli/                    # → ralph-cli/
│   ├── hooks/                  # → claude/hooks/
│   ├── commands/               # → claude/commands/
│   └── skills/                 # → claude/skills/
└── ralph/                      # THIS REPO (target)
```
