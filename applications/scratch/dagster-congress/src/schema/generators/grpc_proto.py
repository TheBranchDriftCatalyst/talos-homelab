"""
gRPC Proto Generator

Generates .proto file for the Knowledge Graph MCP service from the ontology.
Run: python -m schema.generators.grpc_proto
"""

from pathlib import Path

from schema.ontology import ONTOLOGY, PropertyType, get_all_node_types


def _proto_type(prop_type: PropertyType) -> str:
    """Map PropertyType to proto type."""
    mapping = {
        PropertyType.STRING: "string",
        PropertyType.INTEGER: "int64",
        PropertyType.FLOAT: "double",
        PropertyType.BOOLEAN: "bool",
        PropertyType.DATETIME: "string",  # ISO 8601 string
        PropertyType.DATE: "string",  # ISO 8601 date string
        PropertyType.TEXT: "string",
        PropertyType.VECTOR: "repeated float",
    }
    return mapping.get(prop_type, "string")


def generate_grpc_proto() -> str:
    """Generate .proto file from ontology."""
    lines = [
        '// Auto-generated gRPC proto from ontology.py',
        '// DO NOT EDIT - regenerate with: python -m schema.generators.grpc_proto',
        f'// Ontology version: {ONTOLOGY["version"]}',
        '',
        'syntax = "proto3";',
        '',
        'package knowledge_graph;',
        '',
        'option go_package = "github.com/thebranchdriftcatalyst/dagster-congress/grpc";',
        '',
        '// ============================================================================',
        '// Service Definition',
        '// ============================================================================',
        '',
        'service KnowledgeGraph {',
        '  // Discover available MCP tools from all domains',
        '  rpc DiscoverTools(Empty) returns (ToolList);',
        '',
        '  // Get JSON-LD schema for an entity type',
        '  rpc GetSchema(SchemaRequest) returns (JsonLdSchema);',
        '',
        '  // Execute a Cypher query from registered templates',
        '  rpc ExecuteQuery(QueryRequest) returns (QueryResult);',
        '',
        '  // Semantic search using embeddings',
        '  rpc SemanticSearch(SearchRequest) returns (EntityList);',
        '',
        '  // Get entity by ID',
        '  rpc GetEntity(EntityRequest) returns (Entity);',
        '',
        '  // Stream entities matching a filter',
        '  rpc StreamEntities(FilterRequest) returns (stream Entity);',
        '}',
        '',
        '// ============================================================================',
        '// Common Messages',
        '// ============================================================================',
        '',
        'message Empty {}',
        '',
        'message Tool {',
        '  string name = 1;',
        '  string description = 2;',
        '  string cypher_template = 3;',
        '  map<string, string> parameters = 4;',
        '  string domain = 5;',
        '  string entity_type = 6;',
        '}',
        '',
        'message ToolList {',
        '  repeated Tool tools = 1;',
        '}',
        '',
        'message SchemaRequest {',
        '  string entity_type = 1;',
        '}',
        '',
        'message JsonLdSchema {',
        '  string entity_type = 1;',
        '  string context = 2;  // JSON-LD @context as JSON string',
        '  string schema = 3;   // Full schema as JSON string',
        '}',
        '',
        'message QueryRequest {',
        '  string tool_name = 1;',
        '  map<string, string> parameters = 2;',
        '}',
        '',
        'message QueryResult {',
        '  bool success = 1;',
        '  string data = 2;      // JSON serialized result',
        '  string error = 3;',
        '  int64 count = 4;',
        '}',
        '',
        'message SearchRequest {',
        '  string query = 1;',
        '  int32 limit = 2;',
        '  string entity_type = 3;  // Optional: filter by type',
        '  string domain = 4;       // Optional: filter by domain',
        '}',
        '',
        'message EntityRequest {',
        '  string id = 1;',
        '  string entity_type = 2;',
        '}',
        '',
        'message FilterRequest {',
        '  string entity_type = 1;',
        '  map<string, string> filters = 2;',
        '  int32 limit = 3;',
        '  int32 offset = 4;',
        '}',
        '',
        'message EntityList {',
        '  repeated Entity entities = 1;',
        '  int64 total_count = 2;',
        '}',
        '',
        '// ============================================================================',
        '// Entity Messages (generated from ontology)',
        '// ============================================================================',
        '',
        'message Entity {',
        '  string id = 1;',
        '  string entity_type = 2;',
        '  string domain = 3;',
        '  map<string, string> properties = 4;  // Generic properties',
        '  string json_data = 5;                // Full entity as JSON',
        '  repeated float embedding = 6;        // Vector embedding',
        '}',
        '',
    ]

    # Generate specific entity messages for each node type
    for node_type in get_all_node_types():
        lines.extend([
            f'message {node_type.name} {{',
        ])
        field_num = 1
        for prop in node_type.properties:
            proto_type = _proto_type(prop.prop_type)
            lines.append(f'  {proto_type} {prop.name} = {field_num};')
            field_num += 1
        lines.extend([
            '}',
            '',
        ])

    return '\n'.join(lines)


def write_proto_file(output_path: Path | None = None) -> Path:
    """Write proto to file."""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "generated" / "knowledge_graph.proto"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    proto = generate_grpc_proto()
    output_path.write_text(proto)
    return output_path


if __name__ == "__main__":
    output = write_proto_file()
    print(f"Generated gRPC proto: {output}")
    print("\nTo generate Python stubs:")
    print(f"  python -m grpc_tools.protoc -I {output.parent} --python_out=grpc/generated --grpc_python_out=grpc/generated {output}")
