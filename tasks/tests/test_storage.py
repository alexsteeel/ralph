"""Tests for ralph_tasks.storage — MinIO S3 storage module."""

import pytest
from ralph_tasks.storage import (
    _object_key,
    _object_prefix,
    _sanitize_key_component,
)


class TestStorageSanitization:
    """Unit tests for storage key sanitization (no MinIO required)."""

    def test_sanitize_removes_slashes(self):
        """Slashes should be stripped to prevent path traversal."""
        assert _sanitize_key_component("../../etc/passwd") == "etcpasswd"
        assert _sanitize_key_component("a/b/c") == "abc"
        assert _sanitize_key_component("a\\b\\c") == "abc"

    def test_sanitize_removes_null_bytes(self):
        """Null bytes should be stripped."""
        assert _sanitize_key_component("test\x00file") == "testfile"

    def test_sanitize_removes_leading_dots(self):
        """Leading dots should be stripped to prevent hidden files."""
        assert _sanitize_key_component("..hidden") == "hidden"
        assert _sanitize_key_component(".dotfile") == "dotfile"
        assert _sanitize_key_component("normal.txt") == "normal.txt"

    def test_object_key_crafted_project(self):
        """Crafted project name with traversal chars should be sanitized."""
        key = _object_key("../other-project", 1, "file.txt")
        assert key == "other-project/001/file.txt"
        assert ".." not in key

    def test_object_prefix_sanitized(self):
        """_object_prefix should sanitize project names."""
        # Slashes removed, leading dots stripped
        prefix = _object_prefix("../other", 1)
        assert prefix == "other/001/"
        assert ".." not in prefix

        # Slashes removed, no leading dots to strip
        prefix2 = _object_prefix("test/secret", 1)
        assert prefix2 == "testsecret/001/"
        assert "/" not in prefix2.split("/")[0]

    def test_empty_after_sanitize_raises(self):
        """Completely invalid names should raise ValueError."""
        with pytest.raises(ValueError):
            _object_key("///", 1, "file.txt")

        with pytest.raises(ValueError):
            _object_key("project", 1, "///")

        with pytest.raises(ValueError):
            _object_prefix("...", 1)


@pytest.mark.minio
class TestPutAndGet:
    """Test put_bytes and get_object."""

    def test_put_and_get_text(self, minio_storage):
        content = b"Hello, MinIO!"
        result = minio_storage.put_bytes("test-project", 1, "readme.txt", content)
        assert result["name"] == "readme.txt"
        assert result["size"] == len(content)
        assert result["etag"]

        retrieved = minio_storage.get_object("test-project", 1, "readme.txt")
        assert retrieved == content

    def test_put_and_get_binary(self, minio_storage):
        content = bytes(range(256)) * 100  # 25.6KB binary data
        result = minio_storage.put_bytes("test-project", 1, "data.bin", content)
        assert result["size"] == len(content)

        retrieved = minio_storage.get_object("test-project", 1, "data.bin")
        assert retrieved == content

    def test_get_nonexistent(self, minio_storage):
        result = minio_storage.get_object("test-project", 1, "nonexistent.txt")
        assert result is None

    def test_put_overwrites(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "file.txt", b"version 1")
        minio_storage.put_bytes("test-project", 1, "file.txt", b"version 2")

        retrieved = minio_storage.get_object("test-project", 1, "file.txt")
        assert retrieved == b"version 2"

    def test_put_empty_content(self, minio_storage):
        result = minio_storage.put_bytes("test-project", 1, "empty.txt", b"")
        assert result["size"] == 0

        retrieved = minio_storage.get_object("test-project", 1, "empty.txt")
        assert retrieved == b""


@pytest.mark.minio
class TestListObjects:
    """Test list_objects."""

    def test_list_empty(self, minio_storage):
        result = minio_storage.list_objects("test-project", 99)
        assert result == []

    def test_list_multiple(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "a.txt", b"aaa")
        minio_storage.put_bytes("test-project", 1, "b.png", b"bbb")
        minio_storage.put_bytes("test-project", 1, "c.pdf", b"ccc")

        result = minio_storage.list_objects("test-project", 1)
        names = [r["name"] for r in result]
        assert sorted(names) == ["a.txt", "b.png", "c.pdf"]
        for item in result:
            assert item["size"] == 3

    def test_list_isolation_between_tasks(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "task1.txt", b"1")
        minio_storage.put_bytes("test-project", 2, "task2.txt", b"2")

        result1 = minio_storage.list_objects("test-project", 1)
        result2 = minio_storage.list_objects("test-project", 2)

        assert len(result1) == 1
        assert result1[0]["name"] == "task1.txt"
        assert len(result2) == 1
        assert result2[0]["name"] == "task2.txt"

    def test_list_isolation_between_projects(self, minio_storage):
        minio_storage.put_bytes("proj-a", 1, "file.txt", b"a")
        minio_storage.put_bytes("proj-b", 1, "file.txt", b"b")

        result_a = minio_storage.list_objects("proj-a", 1)
        result_b = minio_storage.list_objects("proj-b", 1)

        assert len(result_a) == 1
        assert len(result_b) == 1


@pytest.mark.minio
class TestDeleteObject:
    """Test delete_object and delete_all_objects."""

    def test_delete_existing(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "file.txt", b"data")
        assert minio_storage.delete_object("test-project", 1, "file.txt") is True
        assert minio_storage.get_object("test-project", 1, "file.txt") is None

    def test_delete_nonexistent(self, minio_storage):
        assert minio_storage.delete_object("test-project", 1, "nonexistent.txt") is False

    def test_delete_all_objects(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "a.txt", b"a")
        minio_storage.put_bytes("test-project", 1, "b.txt", b"b")
        minio_storage.put_bytes("test-project", 1, "c.txt", b"c")

        count = minio_storage.delete_all_objects("test-project", 1)
        assert count == 3
        assert minio_storage.list_objects("test-project", 1) == []

    def test_delete_all_empty(self, minio_storage):
        count = minio_storage.delete_all_objects("test-project", 99)
        assert count == 0


@pytest.mark.minio
class TestObjectExists:
    """Test object_exists."""

    def test_exists_true(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "file.txt", b"data")
        assert minio_storage.object_exists("test-project", 1, "file.txt") is True

    def test_exists_false(self, minio_storage):
        assert minio_storage.object_exists("test-project", 1, "nonexistent.txt") is False


@pytest.mark.minio
class TestPresignedUrl:
    """Test get_presigned_url."""

    def test_presigned_url_existing(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "file.txt", b"data")
        url = minio_storage.get_presigned_url("test-project", 1, "file.txt")
        assert url is not None
        assert "file.txt" in url

    def test_presigned_url_nonexistent(self, minio_storage):
        url = minio_storage.get_presigned_url("test-project", 1, "nonexistent.txt")
        assert url is None


@pytest.mark.minio
class TestResetClient:
    """Test reset_client for test isolation."""

    def test_reset_and_reconnect(self, minio_storage):
        minio_storage.put_bytes("test-project", 1, "before.txt", b"before")
        minio_storage.reset_client()

        # After reset, singleton is gone but env vars are still set
        # Next operation should auto-reconnect
        result = minio_storage.get_object("test-project", 1, "before.txt")
        assert result == b"before"
