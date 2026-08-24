"""
Neo4j Graph Loader

Neo4j loader with ontology support and embedding storage.
Creates nodes with JSON-LD annotations for MCP discovery.
"""

import json
from typing import Any

import structlog
from neo4j import GraphDatabase, Driver

from corpus_core.models.entity import ExtractedEntity

logger = structlog.get_logger()


class Neo4jLoader:
    """
    Load entities into Neo4j with ontology support.

    Features:
    - Creates nodes with JSON-LD metadata for MCP discovery
    - Stores embeddings for semantic search
    - Maintains INSTANCE_OF relationships for ontology navigation
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        embedding_service: Any | None = None,
        valid_relationships: set[str] | None = None,
    ):
        """
        Initialize Neo4jLoader.

        Args:
            neo4j_uri: Neo4j connection URI (bolt://host:port)
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password
            embedding_service: Optional EmbeddingService for vector generation
            valid_relationships: Set of valid relationship types (for validation)
        """
        self.driver: Driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password),
        )
        self.embedding_service = embedding_service
        self._valid_relationships = valid_relationships or set()

    def close(self) -> None:
        """Close the Neo4j driver."""
        self.driver.close()

    def __enter__(self) -> "Neo4jLoader":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def load_entity(
        self,
        entity: ExtractedEntity,
        additional_labels: list[str] | None = None,
    ) -> str | None:
        """
        Load a single entity into Neo4j.

        Args:
            entity: ExtractedEntity to load
            additional_labels: Extra labels to add to the node

        Returns:
            Entity ID if successful, None otherwise
        """
        # Generate embedding if service available
        embedding = None
        if self.embedding_service:
            text_repr = self._get_text_representation(entity)
            embedding = self.embedding_service.get_embedding(text_repr)

        # Build labels (primary + additional)
        labels = [entity.entity_type]
        if additional_labels:
            labels.extend(additional_labels)
        labels_str = ":".join(labels)

        # Build properties
        props = {
            **entity.properties,
            "jsonld_schema": json.dumps(entity.jsonld_schema),
            "domain": entity.domain,
            "confidence": entity.confidence,
        }
        if embedding:
            props["embedding"] = embedding

        # Ensure we have an ID
        entity_id = entity.properties.get("id") or self._generate_id(entity)
        props["id"] = entity_id

        # Create/merge node
        with self.driver.session() as session:
            result = session.run(
                f"""
                MERGE (n:{labels_str} {{id: $id}})
                SET n += $props
                RETURN n.id as id
                """,
                id=entity_id,
                props=props,
            )
            record = result.single()
            if record:
                logger.debug("entity_loaded", id=record["id"], type=entity.entity_type)
                return record["id"]

        return None

    def load_entities(self, entities: list[ExtractedEntity]) -> list[str]:
        """Load multiple entities, returning list of IDs."""
        ids = []
        for entity in entities:
            entity_id = self.load_entity(entity)
            if entity_id:
                ids.append(entity_id)
        logger.info("entities_loaded", count=len(ids))
        return ids

    def load_relationship(
        self,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        relationship_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Create a relationship between two entities.

        Returns True if successful.
        """
        if self._valid_relationships and relationship_type not in self._valid_relationships:
            logger.warning("invalid_relationship_type", type=relationship_type)
            return False

        with self.driver.session() as session:
            query = f"""
                MATCH (a:{from_type} {{id: $from_id}})
                MATCH (b:{to_type} {{id: $to_id}})
                MERGE (a)-[r:{relationship_type}]->(b)
                SET r += $props
                RETURN type(r) as rel_type
            """
            result = session.run(
                query,
                from_id=from_id,
                to_id=to_id,
                props=properties or {},
            )
            record = result.single()
            if record:
                logger.debug(
                    "relationship_created",
                    from_id=from_id,
                    to_id=to_id,
                    type=relationship_type,
                )
                return True

        return False

    def load_entity_with_relationships(self, entity: ExtractedEntity) -> str | None:
        """Load entity and create relationships to existing entities."""
        entity_id = self.load_entity(entity)
        if not entity_id:
            return None

        # Create relationships
        for rel in entity.relationships:
            target_type = rel.get("target_type")
            target_id = rel.get("target_id")
            rel_type = rel.get("relationship_type")

            if target_type and target_id and rel_type:
                self.load_relationship(
                    from_id=entity_id,
                    from_type=entity.entity_type,
                    to_id=target_id,
                    to_type=target_type,
                    relationship_type=rel_type,
                )

        return entity_id

    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        entity_type: str | None = None,
        index_name: str = "entity_embedding_vector",
    ) -> list[dict[str, Any]]:
        """
        Search entities by semantic similarity.

        Uses Neo4j vector index for approximate nearest neighbor search.
        """
        if not self.embedding_service:
            logger.warning("embedding_service_not_configured")
            return []

        query_embedding = self.embedding_service.get_embedding(query)

        with self.driver.session() as session:
            # Build type filter
            type_filter = f":{entity_type}" if entity_type else ""

            result = session.run(
                f"""
                CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
                YIELD node, score
                WHERE node{type_filter}
                RETURN node.id as id,
                       labels(node)[0] as type,
                       node.domain as domain,
                       score,
                       properties(node) as properties
                """,
                index_name=index_name,
                embedding=query_embedding,
                limit=limit,
            )

            return [dict(record) for record in result]

    def run_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Run an arbitrary Cypher query.

        Args:
            query: Cypher query string
            params: Query parameters

        Returns:
            List of result records as dicts
        """
        with self.driver.session() as session:
            result = session.run(query, params or {})
            return [dict(record) for record in result]

    def _get_text_representation(self, entity: ExtractedEntity) -> str:
        """Get text representation for embedding."""
        parts = [entity.entity_type]

        # Add key properties
        for key in ["name", "title", "number", "summary", "description", "content"]:
            if key in entity.properties:
                parts.append(str(entity.properties[key]))

        return " ".join(parts)

    def _generate_id(self, entity: ExtractedEntity) -> str:
        """Generate a deterministic ID for an entity."""
        import hashlib

        # Use key identifying properties
        key_parts = [entity.entity_type]
        for prop in ["number", "bioguide_id", "system_code", "cik", "name", "title"]:
            if prop in entity.properties:
                key_parts.append(str(entity.properties[prop]))
                break

        key_str = ":".join(key_parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]
