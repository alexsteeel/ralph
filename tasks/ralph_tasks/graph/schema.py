"""Neo4j schema initialization: constraints, indexes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ralph_tasks.graph.client import GraphClient

# Unique constraints (single-property — Neo4j CE limitation)
CONSTRAINTS = [
    "CREATE CONSTRAINT workspace_name IF NOT EXISTS FOR (w:Workspace) REQUIRE w.name IS UNIQUE",
]

# Regular indexes for frequent queries
INDEXES = [
    "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status)",
    "CREATE INDEX finding_status IF NOT EXISTS FOR (f:Finding) ON (f.status)",
    "CREATE INDEX section_type IF NOT EXISTS FOR (s:Section) ON (s.type)",
    "CREATE INDEX workflow_run_type IF NOT EXISTS FOR (wr:WorkflowRun) ON (wr.type)",
]

# Full-text indexes for search
FULLTEXT_INDEXES = [
    (
        "CREATE FULLTEXT INDEX task_description_ft IF NOT EXISTS "
        "FOR (t:Task) ON EACH [t.description]"
    ),
    (
        "CREATE FULLTEXT INDEX finding_text_ft IF NOT EXISTS "
        "FOR (f:Finding) ON EACH [f.text]"
    ),
]


def ensure_schema(client: GraphClient) -> None:
    """Create all constraints and indexes if they don't exist.

    Safe to call multiple times — all statements use IF NOT EXISTS.
    """
    with client.session() as session:
        for stmt in CONSTRAINTS:
            session.run(stmt)
        for stmt in INDEXES:
            session.run(stmt)
        for stmt in FULLTEXT_INDEXES:
            session.run(stmt)


def drop_schema(client: GraphClient) -> None:
    """Drop all constraints and indexes. Used in tests for cleanup."""
    with client.session() as session:
        # Drop constraints
        result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        for record in result:
            session.run(f"DROP CONSTRAINT {record['name']} IF EXISTS")
        # Drop indexes
        result = session.run("SHOW INDEXES YIELD name, type RETURN name, type")
        for record in result:
            # Skip lookup indexes (system-managed)
            if record["type"] != "LOOKUP":
                session.run(f"DROP INDEX {record['name']} IF EXISTS")
