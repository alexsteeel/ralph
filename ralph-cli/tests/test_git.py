"""Tests for git operations."""

from ralph_cli.git import (
    cleanup_working_dir,
    commit_wip,
    get_current_branch,
    get_uncommitted_changes,
    has_uncommitted_changes,
)


class TestGitOperations:
    """Tests for git operations."""

    def test_get_current_branch(self, temp_git_repo):
        """Test getting current branch."""
        # Default branch might be 'main' or 'master' depending on git config
        branch = get_current_branch(temp_git_repo)
        assert branch in ("main", "master")

    def test_no_uncommitted_changes_initially(self, temp_git_repo):
        """Test clean repo has no uncommitted changes."""
        assert not has_uncommitted_changes(temp_git_repo)
        assert get_uncommitted_changes(temp_git_repo) == []

    def test_detect_uncommitted_changes(self, temp_git_repo):
        """Test detecting uncommitted changes."""
        # Create new file
        (temp_git_repo / "new_file.txt").write_text("new content")

        assert has_uncommitted_changes(temp_git_repo)
        changes = get_uncommitted_changes(temp_git_repo)
        assert "new_file.txt" in changes

    def test_cleanup_working_dir(self, temp_git_repo):
        """Test cleanup removes uncommitted changes."""
        # Create changes
        (temp_git_repo / "new_file.txt").write_text("new content")
        (temp_git_repo / "README.md").write_text("modified")

        assert has_uncommitted_changes(temp_git_repo)

        # Cleanup
        cleaned = cleanup_working_dir(temp_git_repo)

        assert not has_uncommitted_changes(temp_git_repo)
        assert len(cleaned) >= 1
        assert not (temp_git_repo / "new_file.txt").exists()

    def test_commit_wip(self, temp_git_repo):
        """Test creating WIP commit."""
        # Create change
        (temp_git_repo / "wip_file.txt").write_text("work in progress")

        commit_hash = commit_wip(temp_git_repo, "project#1", "testing")

        assert commit_hash is not None
        assert len(commit_hash) > 0
        assert not has_uncommitted_changes(temp_git_repo)

    def test_commit_wip_no_changes(self, temp_git_repo):
        """Test WIP commit with no changes returns None."""
        commit_hash = commit_wip(temp_git_repo, "project#1", "nothing to commit")
        assert commit_hash is None
