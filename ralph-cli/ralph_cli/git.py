"""Git operations using GitPython."""

import logging
from pathlib import Path

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

logger = logging.getLogger(__name__)

# Directories to exclude from cleanup checks
EXCLUDE_PATTERNS = [".claude/"]


def _is_excluded(path: str) -> bool:
    """Check if path should be excluded from cleanup."""
    return any(path.startswith(pattern) for pattern in EXCLUDE_PATTERNS)


def get_repo(working_dir: Path) -> Repo | None:
    """Get git repository for working directory."""
    try:
        return Repo(working_dir)
    except InvalidGitRepositoryError:
        return None


def get_files_to_clean(working_dir: Path) -> tuple[list[str], list[str]]:
    """Get list of files that would be cleaned.

    Excludes files in EXCLUDE_PATTERNS (e.g., .claude/).

    Returns:
        Tuple of (modified_files, untracked_files).
    """
    repo = get_repo(working_dir)
    if not repo:
        return [], []

    modified = []
    untracked = []

    if repo.is_dirty(untracked_files=True):
        for item in repo.index.diff(None):
            if not _is_excluded(item.a_path):
                modified.append(item.a_path)
        untracked = [f for f in repo.untracked_files if not _is_excluded(f)]

    return modified, untracked


def cleanup_working_dir(working_dir: Path) -> list[str]:
    """Reset working directory to clean state.

    Excludes files in EXCLUDE_PATTERNS (e.g., .claude/).

    Runs:
        git checkout -- . (excluding patterns)
        git clean -fd --exclude=<patterns>

    Returns list of cleaned files.
    """
    repo = get_repo(working_dir)
    if not repo:
        return []

    modified, untracked = get_files_to_clean(working_dir)
    cleaned = modified + untracked

    # Reset tracked files (only non-excluded)
    for filepath in modified:
        try:
            repo.git.checkout("--", filepath)
        except GitCommandError as e:
            logger.debug("git checkout %s failed: %s", filepath, e)

    # Remove untracked files (excluding patterns)
    try:
        exclude_args = [f"--exclude={p}" for p in EXCLUDE_PATTERNS]
        repo.git.clean("-fd", *exclude_args)
    except GitCommandError as e:
        logger.debug("git clean failed: %s", e)

    return cleaned


def get_uncommitted_changes(working_dir: Path) -> list[str]:
    """Return list of modified/untracked files.

    Excludes files in EXCLUDE_PATTERNS (e.g., .claude/).
    """
    repo = get_repo(working_dir)
    if not repo:
        return []

    files = []

    # Modified files
    for item in repo.index.diff(None):
        if not _is_excluded(item.a_path):
            files.append(item.a_path)

    # Staged files
    for item in repo.index.diff("HEAD"):
        if not _is_excluded(item.a_path):
            files.append(item.a_path)

    # Untracked files
    for f in repo.untracked_files:
        if not _is_excluded(f):
            files.append(f)

    return list(set(files))


def has_uncommitted_changes(working_dir: Path) -> bool:
    """Check if there are uncommitted changes.

    Excludes files in EXCLUDE_PATTERNS (e.g., .claude/).
    """
    return bool(get_uncommitted_changes(working_dir))


def commit_wip(working_dir: Path, task_ref: str, message: str) -> str | None:
    """Create WIP commit for blocked task.

    Args:
        working_dir: Repository path
        task_ref: Task reference (e.g., "project#1")
        message: Brief description of why blocked

    Returns:
        Commit hash if successful, None otherwise
    """
    repo = get_repo(working_dir)
    if not repo:
        return None

    if not repo.is_dirty(untracked_files=True):
        return None

    try:
        # Stage all changes
        repo.git.add("-A")

        # Create WIP commit
        commit_msg = f"WIP: {task_ref} - blocked: {message}"
        repo.index.commit(commit_msg)

        # Return short hash
        return repo.head.commit.hexsha[:7]
    except GitCommandError as e:
        logger.debug("commit_wip failed: %s", e)
        return None


def get_current_branch(working_dir: Path) -> str | None:
    """Get current branch name."""
    repo = get_repo(working_dir)
    if not repo:
        return None

    try:
        return repo.active_branch.name
    except TypeError:
        # Detached HEAD state
        return None


def create_branch(working_dir: Path, branch_name: str) -> bool:
    """Create and switch to new branch."""
    repo = get_repo(working_dir)
    if not repo:
        return False

    try:
        repo.git.checkout("-b", branch_name)
        return True
    except GitCommandError as e:
        logger.debug("create_branch failed: %s", e)
        return False


def switch_branch(working_dir: Path, branch_name: str) -> bool:
    """Switch to existing branch."""
    repo = get_repo(working_dir)
    if not repo:
        return False

    try:
        repo.git.checkout(branch_name)
        return True
    except GitCommandError as e:
        logger.debug("switch_branch failed: %s", e)
        return False
