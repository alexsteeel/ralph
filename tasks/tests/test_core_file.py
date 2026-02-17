"""
Tests for core_file.py — the file-based core preserved for migration (#11).

Tests file parsing, serialization, and round-trip for task files.
"""

import pytest
from ralph_tasks import core_file as core


@pytest.fixture
def temp_base_dir(monkeypatch, tmp_path):
    """Use a temporary directory for tests."""
    monkeypatch.setattr(core, "BASE_DIR", tmp_path)
    return tmp_path


class TestReviewBlocksRoundTrip:
    """Tests for review/blocks field round-trip through file parser."""

    def test_update_review_after_clearing(self, temp_base_dir):
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task", review="Initial review content")
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == "Initial review content"
        assert task.blocks == ""

        task.review = ""
        core.write_task(project, task)
        task = core.read_task(project, 1)
        assert task.review == ""

        task.review = "New review content"
        core.write_task(project, task)
        task = core.read_task(project, 1)
        assert task.review == "New review content"
        assert task.blocks == ""

    def test_review_and_blocks_independent(self, temp_base_dir):
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1, description="Test task", review="Review content", blocks="Blocks content"
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == "Review content"
        assert task.blocks == "Blocks content"

    def test_empty_review_then_blocks(self, temp_base_dir):
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task", review="", blocks="Some blocking issue")
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == ""
        assert task.blocks == "Some blocking issue"

    def test_multiline_review(self, temp_base_dir):
        project = "test-project"
        core.get_project_dir(project, create=True)

        review_content = "Line 1\nLine 2\nLine 3"
        task = core.Task(number=1, description="Test task", review=review_content)
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == review_content
        assert task.blocks == ""

    def test_task_to_string_and_parse_roundtrip(self, temp_base_dir):
        """Full round-trip: Task -> string -> file -> parse -> Task."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Round trip test",
            status="work",
            module="auth",
            branch="feature/auth",
            started="2026-01-15 10:00",
            body="Task body",
            plan="Task plan",
            report="Task report",
            review="Task review",
            blocks="Task blocks",
            depends_on=[2, 3],
        )
        core.write_task(project, task)

        parsed = core.read_task(project, 1)
        assert parsed.description == "Round trip test"
        assert parsed.status == "work"
        assert parsed.module == "auth"
        assert parsed.branch == "feature/auth"
        assert parsed.started == "2026-01-15 10:00"
        assert parsed.body == "Task body"
        assert parsed.plan == "Task plan"
        assert parsed.report == "Task report"
        assert parsed.review == "Task review"
        assert parsed.blocks == "Task blocks"
        assert parsed.depends_on == [2, 3]
