"""Pytest fixtures for ralph-tasks tests, including Neo4j, MinIO, and PostgreSQL integration."""

import os

import pytest

# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------

# Default test connection parameters.
# In devcontainer with DinD, Neo4j is reachable via 'docker' hostname.
# Outside devcontainer (CI, local), it's typically 'localhost'.
_NEO4J_TEST_USER = "neo4j"
_NEO4J_TEST_PASSWORD = "testpassword123"
_NEO4J_CANDIDATE_URIS = [
    "bolt://docker:17687",  # DinD test compose
    "bolt://localhost:17687",
]


def _get_test_auth() -> tuple[str, str]:
    user = os.environ.get("NEO4J_TEST_USER", _NEO4J_TEST_USER)
    password = os.environ.get("NEO4J_TEST_PASSWORD", _NEO4J_TEST_PASSWORD)
    return user, password


def _resolve_neo4j_uri() -> str | None:
    """Find a working Neo4j URI, trying candidates in order."""
    explicit = os.environ.get("NEO4J_TEST_URI")
    if explicit:
        return explicit

    from neo4j import GraphDatabase

    auth = _get_test_auth()
    for uri in _NEO4J_CANDIDATE_URIS:
        try:
            driver = GraphDatabase.driver(uri, auth=auth)
            driver.verify_connectivity()
            driver.close()
            return uri
        except Exception:
            continue
    return None


# Resolved lazily on first access
_RESOLVED_URI: str | None = None
_URI_CHECKED = False


def _get_neo4j_uri() -> str | None:
    global _RESOLVED_URI, _URI_CHECKED
    if not _URI_CHECKED:
        _RESOLVED_URI = _resolve_neo4j_uri()
        _URI_CHECKED = True
    return _RESOLVED_URI


# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------

_MINIO_TEST_ACCESS_KEY = "minioadmin"
_MINIO_TEST_SECRET_KEY = "minioadmin"
_MINIO_CANDIDATE_ENDPOINTS = [
    "docker:19000",  # DinD test compose
    "localhost:19000",
]


def _get_minio_test_auth() -> tuple[str, str]:
    access_key = os.environ.get("MINIO_TEST_ACCESS_KEY", _MINIO_TEST_ACCESS_KEY)
    secret_key = os.environ.get("MINIO_TEST_SECRET_KEY", _MINIO_TEST_SECRET_KEY)
    return access_key, secret_key


def _resolve_minio_endpoint() -> str | None:
    """Find a working MinIO endpoint, trying candidates in order."""
    explicit = os.environ.get("MINIO_TEST_ENDPOINT")
    if explicit:
        return explicit

    from minio import Minio

    access_key, secret_key = _get_minio_test_auth()

    for endpoint in _MINIO_CANDIDATE_ENDPOINTS:
        try:
            client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
            client.list_buckets()
            return endpoint
        except Exception:
            continue
    return None


_RESOLVED_MINIO: str | None = None
_MINIO_CHECKED = False


def _get_minio_endpoint() -> str | None:
    global _RESOLVED_MINIO, _MINIO_CHECKED
    if not _MINIO_CHECKED:
        _RESOLVED_MINIO = _resolve_minio_endpoint()
        _MINIO_CHECKED = True
    return _RESOLVED_MINIO


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------

_POSTGRES_TEST_USER = "ralph_test"
_POSTGRES_TEST_PASSWORD = "testpassword123"
_POSTGRES_TEST_DB = "ralph_test"
_POSTGRES_CANDIDATE_URIS = [
    f"postgresql://{_POSTGRES_TEST_USER}:{_POSTGRES_TEST_PASSWORD}@docker:15432/{_POSTGRES_TEST_DB}",  # DinD test compose
    f"postgresql://{_POSTGRES_TEST_USER}:{_POSTGRES_TEST_PASSWORD}@localhost:15432/{_POSTGRES_TEST_DB}",
]


def _resolve_postgres_uri() -> str | None:
    """Find a working PostgreSQL URI, trying candidates in order."""
    explicit = os.environ.get("POSTGRES_TEST_URI")
    if explicit:
        return explicit

    import psycopg2

    for uri in _POSTGRES_CANDIDATE_URIS:
        try:
            conn = psycopg2.connect(uri, connect_timeout=3)
            conn.close()
            return uri
        except Exception:
            continue
    return None


_RESOLVED_POSTGRES: str | None = None
_POSTGRES_CHECKED = False


def _get_postgres_uri() -> str | None:
    global _RESOLVED_POSTGRES, _POSTGRES_CHECKED
    if not _POSTGRES_CHECKED:
        _RESOLVED_POSTGRES = _resolve_postgres_uri()
        _POSTGRES_CHECKED = True
    return _RESOLVED_POSTGRES


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "neo4j: mark test as requiring Neo4j")
    config.addinivalue_line("markers", "minio: mark test as requiring MinIO")
    config.addinivalue_line("markers", "postgres: mark test as requiring PostgreSQL")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked with @pytest.mark.neo4j, @pytest.mark.minio, or @pytest.mark.postgres if unavailable."""
    neo4j_uri = _get_neo4j_uri()
    minio_endpoint = _get_minio_endpoint()
    postgres_uri = _get_postgres_uri()

    skip_neo4j = pytest.mark.skip(reason="Neo4j is not available")
    skip_minio = pytest.mark.skip(reason="MinIO is not available")
    skip_postgres = pytest.mark.skip(reason="PostgreSQL is not available")

    for item in items:
        if "neo4j" in item.keywords and neo4j_uri is None:
            item.add_marker(skip_neo4j)
        if "minio" in item.keywords and minio_endpoint is None:
            item.add_marker(skip_minio)
        if "postgres" in item.keywords and postgres_uri is None:
            item.add_marker(skip_postgres)


# ---------------------------------------------------------------------------
# Neo4j fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def neo4j_driver():
    """Session-scoped Neo4j driver."""
    from neo4j import GraphDatabase

    uri = _get_neo4j_uri()
    if uri is None:
        pytest.skip("Neo4j is not available")

    auth = _get_test_auth()
    driver = GraphDatabase.driver(uri, auth=auth)
    driver.verify_connectivity()
    yield driver
    driver.close()


@pytest.fixture
def neo4j_session(neo4j_driver):
    """Per-test Neo4j session with automatic cleanup."""
    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
        yield session


@pytest.fixture
def neo4j_client():
    """Per-test GraphClient with automatic cleanup and close."""
    from ralph_tasks.graph.client import GraphClient

    uri = _get_neo4j_uri()
    if uri is None:
        pytest.skip("Neo4j is not available")

    auth = _get_test_auth()
    client = GraphClient(uri=uri, auth=auth)
    with client.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    yield client
    client.close()


# ---------------------------------------------------------------------------
# MinIO fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minio_client():
    """Session-scoped MinIO client."""
    from minio import Minio

    endpoint = _get_minio_endpoint()
    if endpoint is None:
        pytest.skip("MinIO is not available")

    access_key, secret_key = _get_minio_test_auth()
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    yield client


_MINIO_TEST_BUCKET = "ralph-tasks-test"


@pytest.fixture
def minio_storage(minio_client, monkeypatch):
    """Per-test storage module configured for test MinIO with cleanup.

    Sets environment variables so storage.py connects to the test MinIO.
    Cleans up the test bucket after each test.
    """
    from ralph_tasks import storage

    endpoint = _get_minio_endpoint()
    access_key, secret_key = _get_minio_test_auth()

    monkeypatch.setenv("MINIO_ENDPOINT", endpoint)
    monkeypatch.setenv("MINIO_ACCESS_KEY", access_key)
    monkeypatch.setenv("MINIO_SECRET_KEY", secret_key)
    monkeypatch.setenv("MINIO_BUCKET", _MINIO_TEST_BUCKET)
    monkeypatch.setenv("MINIO_SECURE", "false")

    # Reset singleton to pick up new env vars
    storage.reset_client()

    yield storage

    # Cleanup: remove all objects in test bucket
    try:
        if minio_client.bucket_exists(_MINIO_TEST_BUCKET):
            for obj in minio_client.list_objects(_MINIO_TEST_BUCKET, recursive=True):
                minio_client.remove_object(_MINIO_TEST_BUCKET, obj.object_name)
            minio_client.remove_bucket(_MINIO_TEST_BUCKET)
    except Exception:
        pass

    # Reset singleton again
    storage.reset_client()


# ---------------------------------------------------------------------------
# PostgreSQL fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_database(monkeypatch):
    """Per-test metrics database module configured for test PostgreSQL.

    Sets POSTGRES_URI, resets pool, ensures schema, yields the database module.
    After the test: truncates tables and resets pool.
    """
    from ralph_tasks.metrics import database

    uri = _get_postgres_uri()
    if uri is None:
        pytest.skip("PostgreSQL is not available")

    monkeypatch.setenv("POSTGRES_URI", uri)
    database.reset_pool()
    database.ensure_schema()

    yield database

    # Cleanup: truncate all metrics tables (CASCADE handles FK dependency)
    try:
        with database.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE task_executions, sessions CASCADE")
    except Exception:
        import warnings

        warnings.warn("pg_database fixture: TRUNCATE failed", stacklevel=1)

    database.reset_pool()
