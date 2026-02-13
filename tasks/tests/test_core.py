"""
Test for issue #11: review content written to blocks when review is empty.

Reproduction steps from the task:
1. Create a task with non-empty review
2. Clear the review
3. Write new content to review
4. Read task - content should be in review, not blocks
"""


import pytest
from ralph_tasks import core
from ralph_tasks import mcp as main


@pytest.fixture
def temp_base_dir(monkeypatch, tmp_path):
    """Use a temporary directory for tests."""
    monkeypatch.setattr(core, "BASE_DIR", tmp_path)
    return tmp_path


class TestReviewBlocksBug:
    """Tests for issue #11: review/blocks field confusion."""

    def test_update_review_after_clearing(self, temp_base_dir):
        """
        Bug reproduction: after clearing review and writing new content,
        content should be in review field, not blocks.
        """
        project = "test-project"
        core.get_project_dir(project, create=True)

        # Step 1: Create task with initial review
        task = core.Task(
            number=1,
            description="Test task",
            review="Initial review content",
        )
        core.write_task(project, task)

        # Verify initial state
        task = core.read_task(project, 1)
        assert task.review == "Initial review content"
        assert task.blocks == ""

        # Step 2: Clear review
        task.review = ""
        core.write_task(project, task)

        # Verify cleared
        task = core.read_task(project, 1)
        assert task.review == ""
        assert task.blocks == ""

        # Step 3: Write new content to review
        task.review = "New review content"
        core.write_task(project, task)

        # Step 4: Read and verify - THIS IS THE BUG CHECK
        task = core.read_task(project, 1)
        assert task.review == "New review content", (
            f"Expected review='New review content', got review='{task.review}'"
        )
        assert task.blocks == "", (
            f"Expected blocks='', got blocks='{task.blocks}'"
        )

    def test_review_and_blocks_independent(self, temp_base_dir):
        """Review and blocks fields should be independent."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Test task",
            review="Review content",
            blocks="Blocks content",
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == "Review content"
        assert task.blocks == "Blocks content"

    def test_empty_review_then_blocks(self, temp_base_dir):
        """
        When review is empty but blocks has content,
        they should remain separate.
        """
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Test task",
            review="",
            blocks="Some blocking issue",
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == ""
        assert task.blocks == "Some blocking issue"

    def test_empty_blocks_then_review(self, temp_base_dir):
        """
        When blocks is empty but review has content,
        they should remain separate.
        """
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Test task",
            review="Some review",
            blocks="",
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == "Some review"
        assert task.blocks == ""

    def test_both_empty(self, temp_base_dir):
        """When both review and blocks are empty, they should stay empty."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Test task",
            review="",
            blocks="",
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == ""
        assert task.blocks == ""

    def test_multiline_review(self, temp_base_dir):
        """Multiline review content should be preserved."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        review_content = """Line 1
Line 2
Line 3"""

        task = core.Task(
            number=1,
            description="Test task",
            review=review_content,
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == review_content
        assert task.blocks == ""

    def test_multiline_blocks(self, temp_base_dir):
        """Multiline blocks content should be preserved."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        blocks_content = """Blocker 1
Blocker 2
Blocker 3"""

        task = core.Task(
            number=1,
            description="Test task",
            blocks=blocks_content,
        )
        core.write_task(project, task)

        task = core.read_task(project, 1)
        assert task.review == ""
        assert task.blocks == blocks_content


class TestWebAPIUpdateTask:
    """Tests for web API update_task endpoint."""

    def test_update_review_with_blocks_content_via_api(self, temp_base_dir):
        """
        Bug reproduction: transfer content from blocks to review via API.
        This simulates UI operation of cutting from blocks and pasting to review.
        """
        from fastapi.testclient import TestClient
        from ralph_tasks import web

        project = "test-project"
        core.get_project_dir(project, create=True)

        # Create task with content in blocks, empty review
        task = core.Task(
            number=1,
            description="Test task",
            review="",
            blocks="Content to transfer",
        )
        core.write_task(project, task)

        client = TestClient(web.app)

        # Try to update review (simulates pasting into review field)
        response = client.post(
            f"/api/task/{project}/1",
            json={"review": "Content to transfer", "blocks": ""}
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["ok"] is True
        assert data["task"]["review"] == "Content to transfer"
        assert data["task"]["blocks"] == ""

    def test_update_empty_review_to_content(self, temp_base_dir):
        """Test updating empty review to have content."""
        from fastapi.testclient import TestClient
        from ralph_tasks import web

        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task", review="", blocks="")
        core.write_task(project, task)

        client = TestClient(web.app)
        response = client.post(
            f"/api/task/{project}/1",
            json={"review": "New review content"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task"]["review"] == "New review content"

    def test_clear_blocks_keep_review(self, temp_base_dir):
        """Test clearing blocks while keeping review."""
        from fastapi.testclient import TestClient
        from ralph_tasks import web

        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(
            number=1,
            description="Test task",
            review="Review content",
            blocks="Blocks content",
        )
        core.write_task(project, task)

        client = TestClient(web.app)
        response = client.post(
            f"/api/task/{project}/1",
            json={"blocks": ""}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task"]["review"] == "Review content"
        assert data["task"]["blocks"] == ""

    def test_review_with_markdown_headers(self, temp_base_dir):
        """
        Test that review content with markdown headers (##) is handled correctly.
        This could confuse the parser if headers like '## Blocks' appear in content.
        """
        from fastapi.testclient import TestClient
        from ralph_tasks import web

        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task")
        core.write_task(project, task)

        client = TestClient(web.app)

        # Content with markdown headers that could confuse parser
        review_content = """## Code Simplifier

Some review content here.

## Security Review

More content.

## Blocks

This is NOT the blocks section - it's inside review!
"""
        response = client.post(
            f"/api/task/{project}/1",
            json={"review": review_content}
        )

        assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
        data = response.json()
        assert "## Code Simplifier" in data["task"]["review"]
        assert "## Blocks" in data["task"]["review"]
        assert data["task"]["blocks"] == ""

        # Read back and verify
        task = core.read_task(project, 1)
        assert "## Code Simplifier" in task.review
        # This is the potential bug - "## Blocks" in review might be parsed as blocks section
        assert "This is NOT the blocks section" in task.review, (
            f"Content after '## Blocks' header was lost from review. "
            f"review='{task.review}', blocks='{task.blocks}'"
        )


    def test_transfer_blocks_to_review_multi_field_update(self, temp_base_dir):
        """
        Test UI scenario: cut content from blocks and paste into review.

        This simulates the fixed saveEdit() behavior that sends all fields at once,
        allowing content to be transferred between tabs.

        Steps:
        1. Create task with content in blocks, empty review
        2. Send update with review=blocks_content, blocks="" (simulating UI edit)
        3. Verify both fields updated correctly
        """
        from fastapi.testclient import TestClient
        from ralph_tasks import web

        project = "test-project"
        core.get_project_dir(project, create=True)

        # Create task with content in blocks only
        blocks_content = """## Code Review Results

- Issue 1: Missing error handling
- Issue 2: Needs documentation

## Security Notes

All checks passed.
"""
        task = core.Task(
            number=1,
            description="Test task",
            review="",
            blocks=blocks_content,
        )
        core.write_task(project, task)

        client = TestClient(web.app)

        # Simulate UI saveEdit() - sends all fields at once
        # User cut from blocks, pasted into review
        response = client.post(
            f"/api/task/{project}/1",
            json={
                "body": "",
                "plan": "",
                "report": "",
                "review": blocks_content,  # Content moved here
                "blocks": ""  # Now empty
            }
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["ok"] is True
        assert data["task"]["review"] == blocks_content.strip()
        assert data["task"]["blocks"] == ""

        # Verify by reading back from file
        task = core.read_task(project, 1)
        assert "## Code Review Results" in task.review
        assert "## Security Notes" in task.review
        assert task.blocks == ""


class TestMCPUpdateTask:
    """Tests for MCP update_task function (main.py)."""

    def test_update_review_via_mcp(self, temp_base_dir):
        """Test updating review via MCP update_task function."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        # Create task
        task = core.Task(number=1, description="Test task")
        core.write_task(project, task)

        # Update review via MCP (use .fn to access the underlying function)
        update_task_fn = main.update_task.fn
        result = update_task_fn(project, 1, review="MCP review content")

        assert result["review"] == "MCP review content"
        assert result["blocks"] == ""

        # Verify by reading back
        task = core.read_task(project, 1)
        assert task.review == "MCP review content"
        assert task.blocks == ""

    def test_update_review_after_clearing_via_mcp(self, temp_base_dir):
        """
        Bug reproduction via MCP:
        1. Set review
        2. Clear review
        3. Set new review
        """
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task")
        core.write_task(project, task)

        update_task_fn = main.update_task.fn

        # Step 1: Set initial review
        update_task_fn(project, 1, review="Initial review")

        # Step 2: Clear review
        update_task_fn(project, 1, review="")

        # Step 3: Set new review
        result = update_task_fn(project, 1, review="New review content")

        assert result["review"] == "New review content"
        assert result["blocks"] == ""

        # Verify by reading back
        task = core.read_task(project, 1)
        assert task.review == "New review content"
        assert task.blocks == ""

    def test_update_blocks_via_mcp(self, temp_base_dir):
        """Test that blocks field is NOT updatable via MCP (no blocks param)."""
        project = "test-project"
        core.get_project_dir(project, create=True)

        task = core.Task(number=1, description="Test task", blocks="Initial blocks")
        core.write_task(project, task)

        # MCP update_task doesn't have blocks parameter
        # So blocks should remain unchanged
        update_task_fn = main.update_task.fn
        result = update_task_fn(project, 1, review="Some review")

        assert result["review"] == "Some review"
        assert result["blocks"] == "Initial blocks"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
