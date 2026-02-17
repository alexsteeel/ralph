"""Tests for attachment functions in ralph_tasks.core — MinIO-backed."""

import os
import tempfile

import pytest


@pytest.mark.minio
@pytest.mark.neo4j
class TestAttachmentsCRUD:
    """Test core attachment functions with MinIO backend.

    Requires both Neo4j (for task existence) and MinIO (for storage).
    """

    @pytest.fixture(autouse=True)
    def setup_core(self, neo4j_client, minio_storage, monkeypatch):
        """Set up core module with test Neo4j and MinIO."""
        from ralph_tasks import core

        # Point core to test Neo4j using the client's URI
        monkeypatch.setenv("NEO4J_URI", neo4j_client._uri)
        monkeypatch.setenv("NEO4J_USER", neo4j_client._auth[0])
        monkeypatch.setenv("NEO4J_PASSWORD", neo4j_client._auth[1])

        # Reset core singleton to pick up test config
        core.reset_client()

        # Clean up Neo4j
        with neo4j_client.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

        yield
        core.reset_client()

    @pytest.fixture
    def project_with_task(self):
        """Create a test project with a task."""
        from ralph_tasks import core

        task = core.create_task("test-att", "Test task for attachments")
        return "test-att", task.number

    def test_save_and_list(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        result = core.save_attachment(project, number, "test.txt", b"hello world")
        assert result["name"] == "test.txt"
        assert result["size"] == 11

        attachments = core.list_attachments(project, number)
        assert len(attachments) == 1
        assert attachments[0]["name"] == "test.txt"
        assert attachments[0]["size"] == 11

    def test_save_multiple(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        core.save_attachment(project, number, "a.txt", b"aaa")
        core.save_attachment(project, number, "b.png", b"bbbb")

        attachments = core.list_attachments(project, number)
        assert len(attachments) == 2
        names = sorted(a["name"] for a in attachments)
        assert names == ["a.txt", "b.png"]

    def test_copy_attachment(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"copied content")
            temp_path = f.name

        try:
            result = core.copy_attachment(project, number, temp_path)
            assert result["size"] == 14

            content = core.get_attachment_bytes(project, number, result["name"])
            assert content == b"copied content"
        finally:
            os.unlink(temp_path)

    def test_copy_attachment_with_custom_name(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"data")
            temp_path = f.name

        try:
            result = core.copy_attachment(project, number, temp_path, filename="renamed.txt")
            assert result["name"] == "renamed.txt"

            content = core.get_attachment_bytes(project, number, "renamed.txt")
            assert content == b"data"
        finally:
            os.unlink(temp_path)

    def test_copy_nonexistent_source(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        with pytest.raises(FileNotFoundError):
            core.copy_attachment(project, number, "/nonexistent/file.txt")

    def test_get_attachment_bytes(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        core.save_attachment(project, number, "data.bin", b"\x00\x01\x02\x03")

        content = core.get_attachment_bytes(project, number, "data.bin")
        assert content == b"\x00\x01\x02\x03"

    def test_get_attachment_bytes_not_found(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        content = core.get_attachment_bytes(project, number, "nonexistent.txt")
        assert content is None

    def test_delete_attachment(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        core.save_attachment(project, number, "to_delete.txt", b"delete me")

        assert core.delete_attachment(project, number, "to_delete.txt") is True
        assert core.list_attachments(project, number) == []

    def test_delete_nonexistent_attachment(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        assert core.delete_attachment(project, number, "nonexistent.txt") is False

    def test_delete_task_cleans_attachments(self, project_with_task):
        from ralph_tasks import core, storage

        project, number = project_with_task
        core.save_attachment(project, number, "file1.txt", b"data1")
        core.save_attachment(project, number, "file2.txt", b"data2")

        core.delete_task(project, number)

        # Attachments should be cleaned up
        assert storage.list_objects(project, number) == []

    def test_save_sanitizes_filename(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        result = core.save_attachment(project, number, "../../../etc/passwd", b"hack")
        assert result["name"] == "passwd"

    def test_save_invalid_filename(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        with pytest.raises(ValueError, match="Invalid filename"):
            core.save_attachment(project, number, "", b"no name")

    def test_list_empty(self, project_with_task):
        from ralph_tasks import core

        project, number = project_with_task
        assert core.list_attachments(project, number) == []
