"""
gRPC Service Handlers

Implements the KnowledgeGraph service for MCP tool discovery and queries.
"""

import json
import os
import time
from typing import Iterator

import structlog
from neo4j import GraphDatabase

from schema.ontology import get_all_node_types, get_node_type
from schema.generators.jsonld_context import generate_jsonld_context
from shared.embedding_service import EmbeddingService

logger = structlog.get_logger()

# Import generated proto stubs (generated at build time)
try:
    from mcp.generated import knowledge_graph_pb2 as pb2
    from mcp.generated import knowledge_graph_pb2_grpc as pb2_grpc
except ImportError:
    # Fallback for development
    pb2 = None
    pb2_grpc = None


class KnowledgeGraphServicer:
    """
    gRPC service implementation for Knowledge Graph MCP interface.

    Provides:
    - Tool discovery from ontology
    - JSON-LD schema retrieval
    - Cypher query execution
    - Semantic search via embeddings
    """

    def __init__(self):
        self.neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = os.environ.get("NEO4J_PASSWORD", "neo4j-password")
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

        self._driver = None
        self._embedding_service = None
        self._start_time = time.time()
        self._tool_registry = self._build_tool_registry()

    @property
    def driver(self):
        """Lazy Neo4j driver initialization."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password),
            )
        return self._driver

    @property
    def embedding_service(self):
        """Lazy embedding service initialization."""
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(ollama_url=self.ollama_url)
        return self._embedding_service

    def _build_tool_registry(self) -> dict:
        """Build registry of all MCP tools from ontology."""
        tools = {}
        for node_type in get_all_node_types():
            for tool in node_type.mcp_tools:
                tools[tool.name] = {
                    "tool": tool,
                    "node_type": node_type,
                }
        return tools

    def Health(self, request, context):
        """Health check endpoint."""
        return pb2.HealthResponse(
            healthy=True,
            version="1.0.0",
            uptime_seconds=int(time.time() - self._start_time),
        )

    def DiscoverTools(self, request, context):
        """Return all available MCP tools from the ontology."""
        tools = []
        for node_type in get_all_node_types():
            for mcp_tool in node_type.mcp_tools:
                tool = pb2.Tool(
                    name=mcp_tool.name,
                    description=mcp_tool.description,
                    cypher_template=mcp_tool.cypher_template,
                    parameters=mcp_tool.parameters,
                    domain=node_type.domain,
                    entity_type=node_type.name,
                )
                tools.append(tool)

        logger.info("tools_discovered", count=len(tools))
        return pb2.ToolList(tools=tools, total_count=len(tools))

    def GetSchema(self, request, context):
        """Return JSON-LD schema for an entity type."""
        entity_type = request.entity_type
        node_type = get_node_type(entity_type)

        if not node_type:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Entity type '{entity_type}' not found")
            return pb2.JsonLdSchema()

        # Generate JSON-LD context for this entity
        full_context = generate_jsonld_context()

        # Find schema for requested type
        entity_schema = None
        for item in full_context.get("@graph", []):
            if item.get("@id") == f"kg:{entity_type}":
                entity_schema = item
                break

        return pb2.JsonLdSchema(
            entity_type=entity_type,
            context=json.dumps(full_context.get("@context", {})),
            schema=json.dumps(entity_schema or {}),
        )

    def ExecuteQuery(self, request, context):
        """Execute a Cypher query from a registered tool template."""
        tool_name = request.tool_name
        parameters = dict(request.parameters)

        # Find tool in registry
        if tool_name not in self._tool_registry:
            return pb2.QueryResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                count=0,
            )

        tool_info = self._tool_registry[tool_name]
        cypher = tool_info["tool"].cypher_template

        # Convert parameters to appropriate types
        typed_params = self._convert_parameters(parameters, tool_info["tool"].parameters)

        # Execute query
        start_time = time.time()
        try:
            with self.driver.session() as session:
                result = session.run(cypher, typed_params)
                records = [dict(record) for record in result]

            execution_time = (time.time() - start_time) * 1000

            logger.info(
                "query_executed",
                tool=tool_name,
                count=len(records),
                execution_time_ms=execution_time,
            )

            return pb2.QueryResult(
                success=True,
                data=json.dumps(records, default=str),
                count=len(records),
                execution_time_ms=execution_time,
            )

        except Exception as e:
            logger.error("query_failed", tool=tool_name, error=str(e))
            return pb2.QueryResult(
                success=False,
                error=str(e),
                count=0,
            )

    def SemanticSearch(self, request, context):
        """Semantic search using vector embeddings."""
        query = request.query
        limit = request.limit or 10
        entity_type = request.entity_type or None
        min_score = request.min_score or 0.0

        # Generate query embedding
        query_embedding = self.embedding_service.get_embedding(query)

        # Build type filter
        type_filter = f":{entity_type}" if entity_type else ""

        # Execute vector search
        try:
            with self.driver.session() as session:
                result = session.run(
                    f"""
                    CALL db.index.vector.queryNodes('entity_embedding_vector', $limit, $embedding)
                    YIELD node, score
                    WHERE score >= $min_score
                    {"AND node" + type_filter if type_filter else ""}
                    RETURN node.id as id,
                           labels(node)[0] as type,
                           node.domain as domain,
                           score,
                           properties(node) as properties
                    """,
                    embedding=query_embedding,
                    limit=limit,
                    min_score=min_score,
                )

                entities = []
                for record in result:
                    entity = pb2.Entity(
                        id=record["id"],
                        entity_type=record["type"],
                        domain=record["domain"] or "congressional",
                        properties={k: str(v) for k, v in record["properties"].items() if v},
                        json_data=json.dumps(record["properties"], default=str),
                        score=record["score"],
                    )
                    entities.append(entity)

                logger.info("semantic_search", query=query[:50], count=len(entities))

                return pb2.EntityList(
                    entities=entities,
                    total_count=len(entities),
                    has_more=False,
                )

        except Exception as e:
            logger.error("semantic_search_failed", error=str(e))
            return pb2.EntityList(entities=[], total_count=0, has_more=False)

    def GetEntity(self, request, context):
        """Get a single entity by ID."""
        entity_id = request.id
        entity_type = request.entity_type

        type_filter = f":{entity_type}" if entity_type else ""

        try:
            with self.driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n{type_filter} {{id: $id}})
                    RETURN n.id as id,
                           labels(n)[0] as type,
                           n.domain as domain,
                           properties(n) as properties
                    """,
                    id=entity_id,
                )
                record = result.single()

                if not record:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(f"Entity '{entity_id}' not found")
                    return pb2.Entity()

                return pb2.Entity(
                    id=record["id"],
                    entity_type=record["type"],
                    domain=record["domain"] or "congressional",
                    properties={k: str(v) for k, v in record["properties"].items() if v},
                    json_data=json.dumps(record["properties"], default=str),
                )

        except Exception as e:
            logger.error("get_entity_failed", id=entity_id, error=str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.Entity()

    def StreamEntities(self, request, context) -> Iterator:
        """Stream entities matching filters."""
        entity_type = request.entity_type
        filters = dict(request.filters)
        limit = request.limit or 100
        offset = request.offset or 0

        type_filter = f":{entity_type}" if entity_type else ""

        # Build WHERE clause from filters
        where_clauses = []
        for key, value in filters.items():
            where_clauses.append(f"n.{key} = ${key}")

        where_clause = " AND ".join(where_clauses) if where_clauses else "true"

        try:
            with self.driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n{type_filter})
                    WHERE {where_clause}
                    RETURN n.id as id,
                           labels(n)[0] as type,
                           n.domain as domain,
                           properties(n) as properties
                    SKIP $offset
                    LIMIT $limit
                    """,
                    **filters,
                    offset=offset,
                    limit=limit,
                )

                for record in result:
                    entity = pb2.Entity(
                        id=record["id"],
                        entity_type=record["type"],
                        domain=record["domain"] or "congressional",
                        properties={k: str(v) for k, v in record["properties"].items() if v},
                        json_data=json.dumps(record["properties"], default=str),
                    )
                    yield entity

        except Exception as e:
            logger.error("stream_entities_failed", error=str(e))
            return

    def _convert_parameters(self, params: dict, param_types: dict) -> dict:
        """Convert string parameters to typed values."""
        typed = {}
        for key, value in params.items():
            param_type = param_types.get(key, "string")
            if param_type == "integer":
                typed[key] = int(value)
            elif param_type == "float":
                typed[key] = float(value)
            elif param_type == "boolean":
                typed[key] = value.lower() in ("true", "1", "yes")
            else:
                typed[key] = value
        return typed

    def close(self):
        """Clean up resources."""
        if self._driver:
            self._driver.close()
