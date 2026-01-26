"""
Ontology and schema generation system.

Provides:
- Ontology definitions (NodeType, PropertyDef, RelationshipType)
- Schema generators for Neo4j, JSON-LD, and gRPC
"""

from corpus_core.schema.ontology import (
    PropertyType,
    PropertyDef,
    RelationshipType,
    MCPTool,
    NodeType,
    Ontology,
)

__all__ = [
    "PropertyType",
    "PropertyDef",
    "RelationshipType",
    "MCPTool",
    "NodeType",
    "Ontology",
]
