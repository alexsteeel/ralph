#!/bin/bash
# AI Agents Sandbox - Project Initialization Script
# This script is called automatically by VS Code when opening the project
#
# Example of manual usage:
#   .devcontainer/init.sh /path/to/project

set -e

PROJECT_DIR="${1:-$(pwd)}"

# Initialize the worktree environment
ai-sbx init worktree "$PROJECT_DIR"

# Install workspace packages
if command -v uv >/dev/null 2>&1; then
    echo "Installing workspace packages..."
    (cd "$PROJECT_DIR" && uv sync --all-packages 2>&1 | tail -3)
fi

# Start test services in DinD (neo4j-test, minio-test, postgres-test)
echo "Waiting for Docker to be ready..."
MAX_WAIT=90
WAIT_COUNT=0
while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if docker version >/dev/null 2>&1; then
        echo "Docker is ready!"
        break
    fi
    sleep 3
    WAIT_COUNT=$((WAIT_COUNT + 3))
done

if [ $WAIT_COUNT -ge $MAX_WAIT ]; then
    echo "Warning: Docker did not become ready, skipping test services"
else
    for attempt in 1 2 3; do
        if docker compose -p ralph-tests -f "$PROJECT_DIR/tasks/tests/docker-compose.yaml" up -d 2>&1; then
            echo "Test services started (docker:17687, docker:19000, docker:15432)"
            break
        fi
        echo "Retry $attempt/3 for test services..."
        sleep 15
    done
fi
