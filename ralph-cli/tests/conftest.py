"""Pytest fixtures for ralph tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_env_file(temp_dir):
    """Create temporary .env file."""
    env_path = temp_dir / ".env"
    env_path.write_text("""
TELEGRAM_BOT_TOKEN=test_token_123
TELEGRAM_CHAT_ID=test_chat_456
RECOVERY_ENABLED=true
RECOVERY_DELAYS=60,120,180
CONTEXT_OVERFLOW_MAX_RETRIES=3
""")
    return env_path


@pytest.fixture
def temp_git_repo(temp_dir):
    """Create temporary git repository."""
    import subprocess

    subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=temp_dir,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=temp_dir,
        capture_output=True,
    )

    # Create initial commit
    (temp_dir / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_dir,
        capture_output=True,
    )

    return temp_dir
