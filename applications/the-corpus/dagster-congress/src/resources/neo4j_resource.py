"""Neo4j Dagster Resource."""

import os
from contextlib import contextmanager

from dagster import ConfigurableResource
from neo4j import GraphDatabase, Driver


class Neo4jResource(ConfigurableResource):
    """
    Dagster resource for Neo4j graph database.

    Configuration via environment variables or direct config.
    """

    uri: str = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user: str = os.environ.get("NEO4J_USER", "neo4j")
    password: str = os.environ.get("NEO4J_PASSWORD", "neo4j-password")

    _driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        """Get or create Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
            )
        return self._driver

    @contextmanager
    def get_session(self):
        """Get a Neo4j session as context manager."""
        session = self.driver.session()
        try:
            yield session
        finally:
            session.close()

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        """Run a Cypher query and return results."""
        with self.get_session() as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def close(self) -> None:
        """Close the driver."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def teardown_after_execution(self, context) -> None:
        """Clean up after execution."""
        self.close()
