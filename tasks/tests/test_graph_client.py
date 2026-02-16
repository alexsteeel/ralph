"""Tests for GraphClient: connectivity, sessions, context manager."""

import pytest
from ralph_tasks.graph.client import GraphClient


@pytest.mark.neo4j
class TestGraphClientConnectivity:
    def test_verify_connectivity(self, neo4j_client):
        assert neo4j_client.verify_connectivity() is True

    def test_verify_connectivity_bad_uri(self):
        client = GraphClient(uri="bolt://localhost:19999", auth=("neo4j", "wrong"))
        assert client.verify_connectivity() is False
        client.close()

    def test_lazy_driver_creation(self):
        """Driver should not be created until first access."""
        client = GraphClient(uri="bolt://nonexistent:9999", auth=("neo4j", "test"))
        assert client._driver is None
        # Access driver triggers creation (driver object, not connection)
        _ = client.driver
        assert client._driver is not None
        client.close()

    def test_close_sets_driver_none(self, neo4j_client):
        """After close(), driver should be None."""
        _ = neo4j_client.driver  # ensure created
        neo4j_client.close()
        assert neo4j_client._driver is None

    def test_context_manager(self, neo4j_client):
        """Client should work as context manager and auto-close."""
        uri = neo4j_client._uri
        auth = neo4j_client._auth

        with GraphClient(uri=uri, auth=auth) as client:
            assert client.verify_connectivity() is True
        # After exiting context, driver should be None
        assert client._driver is None

    def test_execute_read(self, neo4j_client):
        result = neo4j_client.execute_read("RETURN 1 AS value")
        assert len(result) == 1
        assert result[0]["value"] == 1

    def test_execute_write(self, neo4j_client):
        neo4j_client.execute_write("CREATE (n:TestNode {name: 'test'})")
        result = neo4j_client.execute_read(
            "MATCH (n:TestNode {name: 'test'}) RETURN n.name AS name"
        )
        assert len(result) == 1
        assert result[0]["name"] == "test"

    def test_session_creation(self, neo4j_client):
        with neo4j_client.session() as session:
            result = session.run("RETURN 42 AS answer")
            record = result.single()
            assert record["answer"] == 42
