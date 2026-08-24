"""
Schema generators.

Generates target schemas from ontology definitions:
- Neo4j Cypher constraints and indexes
- JSON-LD context for MCP discovery
"""

from corpus_core.schema.generators.neo4j_schema import generate_neo4j_schema
from corpus_core.schema.generators.jsonld_context import generate_jsonld_context

__all__ = ["generate_neo4j_schema", "generate_jsonld_context"]
