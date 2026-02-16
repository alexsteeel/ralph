"""Pytest fixtures for ralph-tasks tests, including Neo4j integration."""

import os

import pytest

# Default test connection parameters.
# In devcontainer with DinD, Neo4j is reachable via 'docker' hostname.
# Outside devcontainer (CI, local), it's typically 'localhost'.
_NEO4J_TEST_USER = "neo4j"
_NEO4J_TEST_PASSWORD = "testpassword123"
_NEO4J_CANDIDATE_URIS = ["bolt://docker:7687", "bolt://localhost:7687"]


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


# Resolved once at module load
_RESOLVED_URI: str | None = None
_URI_CHECKED = False


def _get_neo4j_uri() -> str | None:
    global _RESOLVED_URI, _URI_CHECKED
    if not _URI_CHECKED:
        _RESOLVED_URI = _resolve_neo4j_uri()
        _URI_CHECKED = True
    return _RESOLVED_URI


def pytest_configure(config):
    config.addinivalue_line("markers", "neo4j: mark test as requiring Neo4j")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked with @pytest.mark.neo4j if Neo4j is unavailable."""
    uri = _get_neo4j_uri()
    if uri is not None:
        return

    skip_neo4j = pytest.mark.skip(reason="Neo4j is not available")
    for item in items:
        if "neo4j" in item.keywords:
            item.add_marker(skip_neo4j)


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
