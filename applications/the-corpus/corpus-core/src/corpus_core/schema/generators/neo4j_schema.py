"""
Neo4j Schema Generator

Generates Cypher statements for constraints and indexes from the ontology.
"""

from pathlib import Path

from corpus_core.schema.ontology import Ontology, PropertyType


def generate_neo4j_schema(ontology: Ontology) -> str:
    """Generate Cypher schema statements from ontology."""
    statements = [
        "// Auto-generated Neo4j schema from ontology",
        "// DO NOT EDIT - regenerate with schema generator",
        f"// Ontology: {ontology.domain} v{ontology.version}",
        "",
        "// ============================================================================",
        "// Constraints",
        "// ============================================================================",
        "",
    ]

    # Generate constraints for each node type
    for node_type in ontology.get_all_node_types():
        statements.append(f"// {node_type.name} constraints")

        for prop in node_type.properties:
            if prop.unique:
                # Unique constraint
                statements.append(
                    f"CREATE CONSTRAINT {node_type.name.lower()}_{prop.name}_unique "
                    f"IF NOT EXISTS FOR (n:{node_type.name}) REQUIRE n.{prop.name} IS UNIQUE;"
                )
            elif prop.required and not prop.unique:
                # NOT NULL constraint (Neo4j 5.x)
                statements.append(
                    f"CREATE CONSTRAINT {node_type.name.lower()}_{prop.name}_exists "
                    f"IF NOT EXISTS FOR (n:{node_type.name}) REQUIRE n.{prop.name} IS NOT NULL;"
                )

        statements.append("")

    statements.extend([
        "// ============================================================================",
        "// Indexes",
        "// ============================================================================",
        "",
    ])

    # Generate indexes for each node type
    for node_type in ontology.get_all_node_types():
        statements.append(f"// {node_type.name} indexes")

        for prop in node_type.properties:
            if prop.indexed and not prop.unique:  # Unique already creates index
                # Standard B-tree index
                statements.append(
                    f"CREATE INDEX {node_type.name.lower()}_{prop.name}_idx "
                    f"IF NOT EXISTS FOR (n:{node_type.name}) ON (n.{prop.name});"
                )
            elif prop.fulltext:
                # Full-text search index
                statements.append(
                    f"CREATE FULLTEXT INDEX {node_type.name.lower()}_{prop.name}_fulltext "
                    f"IF NOT EXISTS FOR (n:{node_type.name}) ON EACH [n.{prop.name}];"
                )
            elif prop.prop_type == PropertyType.VECTOR:
                # Vector index for embeddings (Neo4j 5.x native)
                statements.append(
                    f"CREATE VECTOR INDEX {node_type.name.lower()}_{prop.name}_vector "
                    f"IF NOT EXISTS FOR (n:{node_type.name}) ON (n.{prop.name}) "
                    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};"
                )

        statements.append("")

    # Generate relationship type constraints if needed
    statements.extend([
        "// ============================================================================",
        "// Relationship Indexes",
        "// ============================================================================",
        "",
    ])

    for rel_type in ontology.get_all_relationship_types():
        for prop in rel_type.properties:
            if prop.indexed:
                statements.append(
                    f"CREATE INDEX {rel_type.name.lower()}_{prop.name}_idx "
                    f"IF NOT EXISTS FOR ()-[r:{rel_type.name}]-() ON (r.{prop.name});"
                )

    return "\n".join(statements)


def write_schema_file(ontology: Ontology, output_path: Path) -> Path:
    """Write schema to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = generate_neo4j_schema(ontology)
    output_path.write_text(schema)
    return output_path
