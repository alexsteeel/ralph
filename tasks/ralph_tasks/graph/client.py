"""Neo4j client wrapper with lazy driver initialization."""

from __future__ import annotations

import os

from neo4j import Driver, GraphDatabase, Session


class GraphClient:
    """Wrapper over neo4j Python driver with lazy initialization.

    Configuration is read from environment variables:
    - NEO4J_URI (default: bolt://localhost:7687)
    - NEO4J_USER (default: neo4j)
    - NEO4J_PASSWORD (default: neo4j)
    """

    def __init__(
        self,
        uri: str | None = None,
        auth: tuple[str, str] | None = None,
    ) -> None:
        self._uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        if auth:
            self._auth = auth
        else:
            user = os.environ.get("NEO4J_USER", "neo4j")
            password = os.environ.get("NEO4J_PASSWORD", "neo4j")
            self._auth = (user, password)
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        """Lazily create the driver on first access."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(self._uri, auth=self._auth)
        return self._driver

    def close(self) -> None:
        """Close the driver connection."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def verify_connectivity(self) -> bool:
        """Check that the database is reachable."""
        try:
            self.driver.verify_connectivity()
            return True
        except Exception:
            return False

    def session(self, **kwargs) -> Session:
        """Create a new session."""
        return self.driver.session(**kwargs)

    def execute_read(self, query: str, **params) -> list[dict]:
        """Run a read query and return results as list of dicts."""
        with self.session() as session:
            result = session.run(query, params)
            return [record.data() for record in result]

    def execute_write(self, query: str, **params) -> list[dict]:
        """Run a write query and return results as list of dicts."""
        with self.session() as session:
            result = session.run(query, params)
            return [record.data() for record in result]

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
