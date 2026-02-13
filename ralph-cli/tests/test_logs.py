"""Tests for logs command."""

from ralph_cli.commands.logs import (
    LOG_DIRS,
    LogType,
    format_size,
    get_log_files,
    resolve_log_path,
)


class TestLogType:
    """Tests for LogType enum."""

    def test_log_types(self):
        """Test all log types are defined."""
        assert LogType.implement.value == "implement"
        assert LogType.plan.value == "plan"
        assert LogType.review.value == "review"
        assert LogType.hooks.value == "hooks"
        assert LogType.all.value == "all"

    def test_log_dirs_mapping(self):
        """Test LOG_DIRS maps to correct directory names."""
        assert LOG_DIRS[LogType.implement] == "ralph-implement"
        assert LOG_DIRS[LogType.plan] == "ralph-plan"
        assert LOG_DIRS[LogType.review] == "reviews"
        assert LOG_DIRS[LogType.hooks] == "hooks"


class TestFormatSize:
    """Tests for format_size function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_size(0) == "0 B"
        assert format_size(500) == "500 B"
        assert format_size(1023) == "1023 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_size(1024) == "1 KB"
        assert format_size(2048) == "2 KB"
        assert format_size(1024 * 500) == "500 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_size(1024 * 1024) == "1 MB"
        assert format_size(1024 * 1024 * 5) == "5 MB"


class TestGetLogFiles:
    """Tests for get_log_files function."""

    def test_returns_list(self):
        """Test returns a list."""
        result = get_log_files()
        assert isinstance(result, list)

    def test_filter_by_type(self):
        """Test filtering by log type."""
        # Should not raise
        result = get_log_files(log_type=LogType.hooks)
        assert isinstance(result, list)

    def test_filter_by_task(self):
        """Test filtering by task reference."""
        result = get_log_files(task_filter="nonexistent#999")
        assert result == []


class TestResolveLogPath:
    """Tests for resolve_log_path function."""

    def test_nonexistent_file(self):
        """Test resolving nonexistent file returns None."""
        result = resolve_log_path("nonexistent_file_12345.log")
        assert result is None

    def test_absolute_path_nonexistent(self):
        """Test absolute path that doesn't exist."""
        result = resolve_log_path("/nonexistent/path/file.log")
        assert result is None
