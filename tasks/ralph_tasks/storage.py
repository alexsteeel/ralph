"""
S3 storage module for task attachments using MinIO.

Provides a lazy-singleton MinIO client with auto-bucket creation,
following the same pattern as graph/client.py for Neo4j.

Configuration via environment variables:
- MINIO_ENDPOINT (default: localhost:9000)
- MINIO_ACCESS_KEY (default: minioadmin)
- MINIO_SECRET_KEY (default: minioadmin)
- MINIO_BUCKET (default: ralph-tasks)
- MINIO_SECURE (default: false)
"""

from __future__ import annotations

import io
import logging
import os
from datetime import timedelta
from pathlib import Path

from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

logger = logging.getLogger("md-task-mcp.storage")

# Default configuration
_DEFAULT_ENDPOINT = "localhost:9000"
_DEFAULT_ACCESS_KEY = "minioadmin"
_DEFAULT_SECRET_KEY = "minioadmin"
_DEFAULT_BUCKET = "ralph-tasks"

# Singleton state
_client: Minio | None = None
_bucket_ensured: bool = False


def _get_client() -> Minio:
    """Get or create the singleton MinIO client."""
    global _client
    if _client is None:
        endpoint = os.environ.get("MINIO_ENDPOINT", _DEFAULT_ENDPOINT)
        access_key = os.environ.get("MINIO_ACCESS_KEY", _DEFAULT_ACCESS_KEY)
        secret_key = os.environ.get("MINIO_SECRET_KEY", _DEFAULT_SECRET_KEY)
        secure = os.environ.get("MINIO_SECURE", "false").lower() in ("true", "1", "yes")

        _client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        logger.info(f"MinIO client created: endpoint={endpoint}, secure={secure}")
    return _client


def _get_bucket() -> str:
    """Get the bucket name from env or default."""
    return os.environ.get("MINIO_BUCKET", _DEFAULT_BUCKET)


def _ensure_bucket() -> None:
    """Create the bucket if it doesn't exist (idempotent)."""
    global _bucket_ensured
    if _bucket_ensured:
        return

    client = _get_client()
    bucket = _get_bucket()

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info(f"Created MinIO bucket: {bucket}")
    _bucket_ensured = True


def _ready() -> tuple[Minio, str]:
    """Ensure bucket exists and return (client, bucket_name).

    Consolidates the repeated _ensure_bucket / _get_client / _get_bucket
    sequence used by every public function.
    """
    _ensure_bucket()
    return _get_client(), _get_bucket()


def _sanitize_key_component(value: str) -> str:
    """Sanitize a component for use in S3 object keys.

    Strips path separators and traversal sequences to prevent key injection.
    """
    # Remove path separators and null bytes
    clean = value.replace("/", "").replace("\\", "").replace("\0", "")
    # Remove leading dots to prevent hidden files / traversal
    clean = clean.lstrip(".")
    return clean


def _object_key(project: str, task_number: int, filename: str) -> str:
    """Build object key: {project}/{NNN}/{filename}.

    Sanitizes project and filename to prevent S3 key injection.
    """
    safe_project = _sanitize_key_component(project)
    safe_filename = _sanitize_key_component(filename)
    if not safe_project or not safe_filename:
        raise ValueError(f"Invalid project or filename: project={project!r}, filename={filename!r}")
    return f"{safe_project}/{task_number:03d}/{safe_filename}"


def reset_client() -> None:
    """Reset the MinIO client and bucket state (for testing)."""
    global _client, _bucket_ensured
    _client = None
    _bucket_ensured = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def put_bytes(project: str, task_number: int, filename: str, content: bytes) -> dict:
    """Upload content to MinIO.

    Returns:
        {"name": filename, "size": int, "etag": str}
    """
    client, bucket = _ready()
    key = _object_key(project, task_number, filename)

    result = client.put_object(
        bucket,
        key,
        io.BytesIO(content),
        length=len(content),
    )
    logger.info(f"Uploaded: {key} ({len(content)} bytes)")
    return {"name": filename, "size": len(content), "etag": result.etag}


def get_object(project: str, task_number: int, filename: str) -> bytes | None:
    """Download object content from MinIO.

    Returns bytes or None if not found.
    """
    client, bucket = _ready()
    key = _object_key(project, task_number, filename)

    try:
        response = client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except S3Error as e:
        if e.code == "NoSuchKey":
            return None
        raise


def _object_prefix(project: str, task_number: int) -> str:
    """Build sanitized object prefix: {project}/{NNN}/."""
    safe_project = _sanitize_key_component(project)
    if not safe_project:
        raise ValueError(f"Invalid project name: {project!r}")
    return f"{safe_project}/{task_number:03d}/"


def list_objects(project: str, task_number: int) -> list[dict]:
    """List all objects for a task.

    Returns list of {"name": filename, "size": int}.
    """
    client, bucket = _ready()
    prefix = _object_prefix(project, task_number)

    return [
        {"name": Path(obj.object_name).name, "size": obj.size}
        for obj in client.list_objects(bucket, prefix=prefix)
    ]


def delete_object(project: str, task_number: int, filename: str) -> bool:
    """Delete an object from MinIO.

    Returns True if deleted, False if not found.
    """
    if not object_exists(project, task_number, filename):
        return False

    client, bucket = _ready()
    key = _object_key(project, task_number, filename)
    client.remove_object(bucket, key)
    logger.info(f"Deleted: {key}")
    return True


def delete_all_objects(project: str, task_number: int) -> int:
    """Delete all objects for a task.

    Returns the number of objects deleted.
    """
    client, bucket = _ready()
    prefix = _object_prefix(project, task_number)

    count = 0
    for obj in client.list_objects(bucket, prefix=prefix):
        client.remove_object(bucket, obj.object_name)
        count += 1

    if count:
        logger.info(f"Deleted {count} objects with prefix: {prefix}")
    return count


def object_exists(project: str, task_number: int, filename: str) -> bool:
    """Check if an object exists in MinIO."""
    client, bucket = _ready()
    key = _object_key(project, task_number, filename)

    try:
        client.stat_object(bucket, key)
        return True
    except S3Error as e:
        if e.code == "NoSuchKey":
            return False
        raise


def migrate_project_prefix(old_project: str, new_project: str) -> int:
    """Migrate all objects from old project prefix to new project prefix.

    Copies objects to the new prefix and removes the old ones.
    Returns the number of objects migrated.
    """
    client, bucket = _ready()

    old_prefix = _sanitize_key_component(old_project) + "/"
    new_prefix = _sanitize_key_component(new_project) + "/"

    if old_prefix == new_prefix:
        logger.warning(
            f"MinIO prefix collision: '{old_project}' and '{new_project}' "
            f"map to identical sanitized prefix '{old_prefix}'. Objects not migrated."
        )
        return 0

    count = 0
    for obj in client.list_objects(bucket, prefix=old_prefix, recursive=True):
        old_key = obj.object_name
        new_key = new_prefix + old_key[len(old_prefix) :]
        client.copy_object(bucket, new_key, CopySource(bucket, old_key))
        client.remove_object(bucket, old_key)
        count += 1

    if count:
        logger.info(f"Migrated {count} objects: {old_prefix} -> {new_prefix}")
    return count


def get_presigned_url(
    project: str, task_number: int, filename: str, expires_seconds: int = 3600
) -> str | None:
    """Generate a presigned URL for downloading an object.

    Returns URL string or None if object doesn't exist.
    """
    if not object_exists(project, task_number, filename):
        return None

    client, bucket = _ready()
    key = _object_key(project, task_number, filename)

    return client.presigned_get_object(bucket, key, expires=timedelta(seconds=expires_seconds))
