#!/bin/bash
# Sync claude/ from repo to ~/.claude/ on the host.
# Usage: ./claude/sync.sh [--dry-run]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${HOME}/.claude"
DRY_RUN=false

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

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

        $DRY_RUN || cp "$f" "$dst/$name"
    done

    if [[ $updated -eq 0 ]]; then
        echo "  ✓ ${dir}/ (${count} files, all up to date)"
    else
        echo "  → ${dir}/: ${updated}/${count} synced"
    fi
}

echo "Syncing ${REPO_DIR} → ${TARGET_DIR}"
$DRY_RUN && echo "(dry run)"
echo ""

sync_dir commands
sync_dir hooks
sync_dir skills

echo ""
echo "Done."
