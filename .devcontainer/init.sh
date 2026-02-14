#!/bin/bash
# AI Agents Sandbox - Project Initialization Script
# This script is called automatically by VS Code when opening the project
#
# Example of manual usage:
#   .devcontainer/init.sh /path/to/project

PROJECT_DIR="${1:-$(pwd)}"

# Initialize the worktree environment
ai-sbx init worktree "$PROJECT_DIR"