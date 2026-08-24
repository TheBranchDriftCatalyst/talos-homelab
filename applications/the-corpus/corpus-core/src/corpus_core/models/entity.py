"""
Extracted Entity Model

Entity with JSON-LD annotations for MCP tool discovery.
"""

from typing import Any

from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    """
    Entity extracted from text with MCP annotations.

    Includes:
    - Extracted properties from NER
    - JSON-LD schema for semantic web compatibility
    - MCP tool definitions for query discovery
    """

    entity_type: str = Field(description="Type of entity (e.g., 'Bill', 'Company', 'Person')")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted properties"
    )
    relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Relationships to other entities"
    )

    # Extraction metadata
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score"
    )
    source_span: str = Field(
        default="",
        description="Source text span this was extracted from"
    )

    # JSON-LD annotation for MCP discovery
    jsonld_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON-LD schema with @context, @type, and mcp:tools"
    )

    # Domain
    domain: str = Field(default="generic", description="Domain this entity belongs to")

    # Embedding (set by loader)
    embedding: list[float] | None = Field(default=None, description="Vector embedding")

    @property
    def id(self) -> str | None:
        """Get entity ID from properties."""
        for key in ["id", "number", "bioguide_id", "system_code", "cik", "accession_number"]:
            if key in self.properties:
                return str(self.properties[key])
        return None

    @property
    def mcp_tools(self) -> list[dict[str, Any]]:
        """Get MCP tools from JSON-LD schema."""
        return self.jsonld_schema.get("mcp:tools", [])

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible properties dict."""
        import json

        props = dict(self.properties)
        props["jsonld_schema"] = json.dumps(self.jsonld_schema)
        props["domain"] = self.domain
        props["confidence"] = self.confidence

        if self.embedding:
            props["embedding"] = self.embedding

        return props

    def to_training_annotation(self) -> dict[str, Any]:
        """Convert to a training data annotation format."""
        return {
            "entity_type": self.entity_type,
            "text": self.source_span,
            "confidence": self.confidence,
            "properties": self.properties,
        }
