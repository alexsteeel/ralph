"""Tests for schema initialization: constraints and indexes."""

import pytest
from ralph_tasks.graph.schema import drop_schema, ensure_schema


@pytest.mark.neo4j
class TestSchemaInit:
    def test_ensure_schema_creates_constraints(self, neo4j_client):
        """Constraints should be created after ensure_schema()."""
        ensure_schema(neo4j_client)

        with neo4j_client.session() as session:
            result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            names = {r["name"] for r in result}
            assert "workspace_name" in names

    def test_ensure_schema_creates_indexes(self, neo4j_client):
        """Regular indexes should be created after ensure_schema()."""
        ensure_schema(neo4j_client)

        with neo4j_client.session() as session:
            result = session.run(
                "SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name, type"
            )
            index_map = {r["name"]: r["type"] for r in result}
            assert "task_status" in index_map
            assert "finding_status" in index_map
            assert "section_type" in index_map
            assert "workflow_run_type" in index_map

    def test_ensure_schema_creates_fulltext_indexes(self, neo4j_client):
        """Full-text indexes should be created."""
        ensure_schema(neo4j_client)

        with neo4j_client.session() as session:
            result = session.run(
                "SHOW INDEXES YIELD name, type WHERE type = 'FULLTEXT' RETURN name"
            )
            names = {r["name"] for r in result}
            assert "task_title_ft" in names
            assert "finding_text_ft" in names

    def test_ensure_schema_idempotent(self, neo4j_client):
        """Calling ensure_schema() twice should not raise errors."""
        ensure_schema(neo4j_client)
        ensure_schema(neo4j_client)

        with neo4j_client.session() as session:
            result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            names = [r["name"] for r in result]
            # Should not have duplicate constraints
            assert len(names) == len(set(names))

    def test_drop_schema(self, neo4j_client):
        """drop_schema() should remove all constraints and non-lookup indexes."""
        ensure_schema(neo4j_client)
        drop_schema(neo4j_client)

        with neo4j_client.session() as session:
            result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            constraints = list(result)
            assert len(constraints) == 0

            result = session.run("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name")
            indexes = list(result)
            assert len(indexes) == 0
