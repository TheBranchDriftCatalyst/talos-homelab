"""
Ontology Definitions

Core ontology types for defining domain schemas.
All entity types, properties, and relationships are defined using these primitives.
Schema generators consume this to produce:
- Neo4j constraints and indexes (schema.cypher)
- gRPC proto definitions
- JSON-LD context (for MCP tool discovery)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PropertyType(Enum):
    """Supported property types mapped to target schemas."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    DATE = "date"
    TEXT = "text"  # Long text, indexed for full-text search
    VECTOR = "vector"  # Embedding vector


@dataclass
class PropertyDef:
    """Property definition with type and constraints."""

    name: str
    prop_type: PropertyType
    required: bool = False
    indexed: bool = False
    unique: bool = False
    fulltext: bool = False  # Full-text search index
    description: str = ""


@dataclass
class RelationshipType:
    """Relationship definition between node types."""

    name: str
    from_node: str
    to_node: str
    properties: list[PropertyDef] = field(default_factory=list)
    description: str = ""


@dataclass
class MCPTool:
    """MCP tool definition for entity discovery and queries."""

    name: str
    description: str
    cypher_template: str
    parameters: dict[str, str]  # param_name -> type


@dataclass
class NodeType:
    """Node type definition with properties, relationships, and MCP tools."""

    name: str
    properties: list[PropertyDef]
    description: str
    domain: str = "generic"
    # Ontology links
    schema_org_type: str | None = None  # schema.org mapping
    superclass: str | None = None
    # MCP integration
    mcp_tools: list[MCPTool] = field(default_factory=list)
    # Labels (for multi-label nodes)
    additional_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "schema_org_type": self.schema_org_type,
            "properties": [
                {
                    "name": p.name,
                    "description": p.description,
                    "type": p.prop_type.value,
                    "required": p.required,
                    "indexed": p.indexed,
                    "unique": p.unique,
                    "fulltext": p.fulltext,
                }
                for p in self.properties
            ],
            "mcp_tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "cypher_template": t.cypher_template,
                    "parameters": t.parameters,
                }
                for t in self.mcp_tools
            ],
        }


class Ontology:
    """
    Ontology registry for a domain.

    Manages node types and relationships for a specific domain.
    """

    def __init__(
        self,
        domain: str,
        version: str = "1.0.0",
        description: str = "",
    ):
        self.domain = domain
        self.version = version
        self.description = description
        self._nodes: dict[str, NodeType] = {}
        self._relationships: dict[str, RelationshipType] = {}

    def register_node_type(self, node_type: NodeType) -> None:
        """Register a node type."""
        self._nodes[node_type.name] = node_type

    def register_relationship_type(self, rel_type: RelationshipType) -> None:
        """Register a relationship type."""
        self._relationships[rel_type.name] = rel_type

    def get_node_type(self, name: str) -> NodeType | None:
        """Get a node type by name."""
        return self._nodes.get(name)

    def get_all_node_types(self) -> list[NodeType]:
        """Get all node types."""
        return list(self._nodes.values())

    def get_all_relationship_types(self) -> list[RelationshipType]:
        """Get all relationship types."""
        return list(self._relationships.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "domain": self.domain,
            "version": self.version,
            "description": self.description,
            "nodes": {name: nt.to_dict() for name, nt in self._nodes.items()},
            "relationships": {
                name: {
                    "name": rt.name,
                    "from_node": rt.from_node,
                    "to_node": rt.to_node,
                    "description": rt.description,
                }
                for name, rt in self._relationships.items()
            },
        }


# Common properties used across multiple node types
COMMON_PROPS = [
    PropertyDef(
        "id",
        PropertyType.STRING,
        required=True,
        unique=True,
        description="Unique identifier",
    ),
    PropertyDef(
        "embedding",
        PropertyType.VECTOR,
        description="Semantic embedding vector for similarity search",
    ),
    PropertyDef(
        "created_at",
        PropertyType.DATETIME,
        description="When the entity was ingested",
    ),
    PropertyDef(
        "updated_at",
        PropertyType.DATETIME,
        description="Last update timestamp",
    ),
    PropertyDef(
        "source_url",
        PropertyType.STRING,
        description="Source URL",
    ),
]


def create_common_properties() -> list[PropertyDef]:
    """Create a fresh copy of common properties."""
    return [
        PropertyDef(
            "id",
            PropertyType.STRING,
            required=True,
            unique=True,
            description="Unique identifier",
        ),
        PropertyDef(
            "embedding",
            PropertyType.VECTOR,
            description="Semantic embedding vector for similarity search",
        ),
        PropertyDef(
            "created_at",
            PropertyType.DATETIME,
            description="When the entity was ingested",
        ),
        PropertyDef(
            "updated_at",
            PropertyType.DATETIME,
            description="Last update timestamp",
        ),
        PropertyDef(
            "source_url",
            PropertyType.STRING,
            description="Source URL",
        ),
    ]
