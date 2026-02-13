"""Tests for executor module."""

from ralph_cli.executor import build_prompt, expand_task_ranges


class TestExpandTaskRanges:
    """Tests for expand_task_ranges function."""

    def test_single_numbers(self):
        """Test expanding single task numbers."""
        assert expand_task_ranges(["1", "2", "3"]) == [1, 2, 3]
        assert expand_task_ranges(["5"]) == [5]

    def test_range(self):
        """Test expanding range notation."""
        assert expand_task_ranges(["1-3"]) == [1, 2, 3]
        assert expand_task_ranges(["5-8"]) == [5, 6, 7, 8]

    def test_mixed(self):
        """Test expanding mixed ranges and singles."""
        assert expand_task_ranges(["1-4", "6", "8-10"]) == [1, 2, 3, 4, 6, 8, 9, 10]
        assert expand_task_ranges(["1", "3-5", "7"]) == [1, 3, 4, 5, 7]

    def test_invalid_skipped(self):
        """Test that invalid values are skipped."""
        assert expand_task_ranges(["1", "invalid", "3"]) == [1, 3]
        assert expand_task_ranges(["abc"]) == []

    def test_empty(self):
        """Test empty input."""
        assert expand_task_ranges([]) == []


class TestBuildPrompt:
    """Tests for build_prompt function."""

    def test_basic(self):
        """Test basic prompt building."""
        prompt = build_prompt("ralph-implement-python-task", "myproject#1")
        assert prompt == "/ralph-implement-python-task myproject#1"

    def test_with_recovery_note(self):
        """Test prompt with recovery note."""
        prompt = build_prompt(
            "ralph-implement-python-task",
            "myproject#1",
            recovery_note="Previous attempt failed",
        )
        assert "Previous attempt failed" in prompt
        assert "/ralph-implement-python-task myproject#1" in prompt
