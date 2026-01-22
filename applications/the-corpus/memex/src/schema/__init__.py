"""Schema module - Single source of truth for all entity definitions."""

from .ontology import (
    NodeType,
    RelationshipType,
    PropertyType,
    ONTOLOGY,
    get_node_type,
    get_all_node_types,
    get_all_relationship_types,
)

__all__ = [
    "NodeType",
    "RelationshipType",
    "PropertyType",
    "ONTOLOGY",
    "get_node_type",
    "get_all_node_types",
    "get_all_relationship_types",
]
