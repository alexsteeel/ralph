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

# Test services (neo4j-test, minio-test, postgres-test) are started
# inside the container via init.secure.sh (postCreateCommand)
# where DOCKER_HOST points to the isolated DinD daemon.
