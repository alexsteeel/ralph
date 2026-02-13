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
