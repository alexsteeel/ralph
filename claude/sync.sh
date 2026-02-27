#!/bin/bash
# Sync claude config, update packages and rebuild images after code changes.
# Usage: ./claude/sync.sh [--no-cache]
set -euo pipefail

NO_CACHE=""
if [[ "${1:-}" == "--no-cache" ]]; then
    NO_CACHE="--no-cache"
fi

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
MONOREPO_ROOT="$(cd "${REPO_DIR}/.." && pwd)"
TARGET_DIR="${HOME}/.claude"

sync_dir() {
    local dir="$1"
    local src="${REPO_DIR}/${dir}"
    local dst="${TARGET_DIR}/${dir}"

    [[ -d "$src" ]] || return 0
    mkdir -p "$dst"

    local count=0
    local updated=0
    for f in "$src"/*; do
        [[ -f "$f" ]] || continue
        local name
        name=$(basename "$f")
        count=$((count + 1))

        if [[ -f "$dst/$name" ]] && diff -q "$f" "$dst/$name" >/dev/null 2>&1; then
            continue
        fi

        updated=$((updated + 1))
        if [[ -f "$dst/$name" ]]; then
            echo "  ↻ ${dir}/${name}"
        else
            echo "  + ${dir}/${name}"
        fi

        cp "$f" "$dst/$name"
    done

    if [[ $updated -eq 0 ]]; then
        echo "  ✓ ${dir}/ (${count} files, all up to date)"
    else
        echo "  → ${dir}/: ${updated}/${count} synced"
    fi
}

# --- 1. Sync config files ---
echo "=== Syncing config: ${REPO_DIR} → ${TARGET_DIR}"
echo ""

sync_dir commands
sync_dir hooks
sync_dir skills

# --- 2. Update workspace packages ---
echo ""
echo "=== Updating workspace packages"

if ! command -v uv >/dev/null 2>&1; then
    echo "  ⚠ uv not found, skipping"
else
    (cd "$MONOREPO_ROOT" && uv sync --all-packages 2>&1 | tail -5)
fi

# --- 3. Reinstall system packages ---
# Updates CLI commands (/usr/local/bin/ralph, ralph-tasks-web, ai-sbx)
# that were installed at container build time and became stale after code changes.
echo ""
echo "=== Reinstalling system packages"

if ! command -v uv >/dev/null 2>&1; then
    echo "  ⚠ uv not found, skipping"
else
    for pkg in tasks ralph-cli sandbox; do
        local_dir="${MONOREPO_ROOT}/${pkg}"
        [[ -f "$local_dir/pyproject.toml" ]] || continue

        if uv pip install --system --break-system-packages --no-cache "$local_dir" 2>/dev/null; then
            echo "  ✓ ${pkg}/"
        else
            echo "  ✗ ${pkg}/ (failed)"
        fi
    done
fi

# --- 4. Rebuild Docker images ---
echo ""
echo "=== Rebuilding Docker images"

RALPH_TASKS_IMAGE_BEFORE=$(docker inspect ai-sbx-ralph-tasks:latest --format='{{.Id}}' 2>/dev/null || echo "none")

if ! command -v ai-sbx >/dev/null 2>&1; then
    echo "  ⚠ ai-sbx not found, skipping"
else
    ai-sbx image build --force $NO_CACHE
fi

# --- 5. Restart ralph-tasks container (only if image changed) ---
RALPH_TASKS_IMAGE_AFTER=$(docker inspect ai-sbx-ralph-tasks:latest --format='{{.Id}}' 2>/dev/null || echo "none")

if [[ "$RALPH_TASKS_IMAGE_BEFORE" != "$RALPH_TASKS_IMAGE_AFTER" ]]; then
    echo ""
    echo "=== Restarting ralph-tasks container (image changed)"

    COMPOSE_FILE="${HOME}/.ai-sbx/share/docker-proxy/docker-compose.yaml"
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        echo "  ⚠ ${COMPOSE_FILE} not found, skipping"
    elif ! docker compose -f "$COMPOSE_FILE" ps ralph-tasks --status running -q 2>/dev/null | grep -q .; then
        echo "  ⚠ ralph-tasks not running, skipping"
    else
        docker compose -f "$COMPOSE_FILE" up -d ralph-tasks 2>&1 | sed 's/^/  /'
        echo "  ✓ ralph-tasks restarted"
    fi
fi

echo ""
echo "Done."
