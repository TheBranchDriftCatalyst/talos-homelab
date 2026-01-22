"""
JSON-LD Context Generator

Generates JSON-LD context for MCP tool discovery from the ontology.
Run: python -m schema.generators.jsonld_context
"""

import json
from pathlib import Path

from schema.ontology import ONTOLOGY, PropertyType, get_all_node_types


def _jsonld_type(prop_type: PropertyType) -> str:
    """Map PropertyType to JSON-LD/XSD type."""
    mapping = {
        PropertyType.STRING: "xsd:string",
        PropertyType.INTEGER: "xsd:integer",
        PropertyType.FLOAT: "xsd:decimal",
        PropertyType.BOOLEAN: "xsd:boolean",
        PropertyType.DATETIME: "xsd:dateTime",
        PropertyType.DATE: "xsd:date",
        PropertyType.TEXT: "xsd:string",
        PropertyType.VECTOR: "schema:ItemList",
    }
    return mapping.get(prop_type, "xsd:string")


def generate_jsonld_context() -> dict:
    """Generate JSON-LD context from ontology."""
    context = {
        "@context": {
            # Standard vocabularies
            "@vocab": "https://schema.org/",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "schema": "https://schema.org/",
            # Custom vocabularies
            "congress": "https://api.congress.gov/v3/",
            "mcp": "https://mcp.anthropic.com/schema/",
            "kg": "https://knowledge-graph.local/",
        },
        "@graph": [],
    }

    # Generate entity schemas
    for node_type in get_all_node_types():
        entity_schema = {
            "@type": node_type.schema_org_type or "Thing",
            "@id": f"kg:{node_type.name}",
            "kg:domain": node_type.domain,
            "kg:description": node_type.description,
            # Properties
            "kg:properties": {},
            # MCP Tools
            "mcp:tools": [],
        }

        # Add properties
        for prop in node_type.properties:
            if prop.name not in ["id", "embedding", "created_at", "updated_at"]:
                entity_schema["kg:properties"][prop.name] = {
                    "@type": _jsonld_type(prop.prop_type),
                    "kg:required": prop.required,
                    "kg:indexed": prop.indexed,
                    "kg:description": prop.description,
                }

        # Add MCP tools
        for tool in node_type.mcp_tools:
            entity_schema["mcp:tools"].append({
                "mcp:name": tool.name,
                "mcp:description": tool.description,
                "mcp:cypher": tool.cypher_template,
                "mcp:parameters": {
                    k: {"@type": f"xsd:{v}"} for k, v in tool.parameters.items()
                },
            })

        context["@graph"].append(entity_schema)

    return context


def write_context_file(output_path: Path | None = None) -> Path:
    """Write JSON-LD context to file."""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "generated" / "context.jsonld"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    context = generate_jsonld_context()
    output_path.write_text(json.dumps(context, indent=2))
    return output_path


if __name__ == "__main__":
    output = write_context_file()
    print(f"Generated JSON-LD context: {output}")
