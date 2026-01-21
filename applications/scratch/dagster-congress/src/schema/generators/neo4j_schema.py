"""
Neo4j Schema Generator

Generates Cypher statements for constraints and indexes from the ontology.
Run: python -m schema.generators.neo4j_schema
"""

from pathlib import Path

from schema.ontology import (
    ONTOLOGY,
    PropertyType,
    get_all_node_types,
    get_all_relationship_types,
)


def generate_neo4j_schema() -> str:
    """Generate Cypher schema statements from ontology."""
    statements = [
        "// Auto-generated Neo4j schema from ontology.py",
        "// DO NOT EDIT - regenerate with: python -m schema.generators.neo4j_schema",
        f"// Ontology version: {ONTOLOGY['version']}",
        "",
        "// ============================================================================",
        "// Constraints",
        "// ============================================================================",
        "",
    ]

    # Generate constraints for each node type
    for node_type in get_all_node_types():
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
    for node_type in get_all_node_types():
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

    for rel_type in get_all_relationship_types():
        for prop in rel_type.properties:
            if prop.indexed:
                statements.append(
                    f"CREATE INDEX {rel_type.name.lower()}_{prop.name}_idx "
                    f"IF NOT EXISTS FOR ()-[r:{rel_type.name}]-() ON (r.{prop.name});"
                )

    return "\n".join(statements)


def write_schema_file(output_path: Path | None = None) -> Path:
    """Write schema to file."""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "generated" / "schema.cypher"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = generate_neo4j_schema()
    output_path.write_text(schema)
    return output_path


if __name__ == "__main__":
    output = write_schema_file()
    print(f"Generated Neo4j schema: {output}")
    print("\nTo apply:")
    print(f"  cat {output} | cypher-shell -u neo4j -p <password>")
