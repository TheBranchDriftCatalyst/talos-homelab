"""
Master Ontology Definitions - SINGLE SOURCE OF TRUTH

All entity types, properties, and relationships are defined here ONCE.
Schema generators in generators/ consume this to produce:
- Neo4j constraints and indexes (schema.cypher)
- gRPC proto definitions (knowledge_graph.proto)
- GraphQL type hints (for @neo4j/introspector augmentation)
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
    domain: str = "congressional"
    # Ontology links
    schema_org_type: str | None = None  # schema.org mapping
    superclass: str | None = None
    # MCP integration
    mcp_tools: list[MCPTool] = field(default_factory=list)
    # Labels (for multi-label nodes)
    additional_labels: list[str] = field(default_factory=list)


# ============================================================================
# Congressional Domain Ontology
# ============================================================================

# Common properties used across multiple node types
COMMON_PROPS = [
    PropertyDef("id", PropertyType.STRING, required=True, unique=True, description="Unique identifier"),
    PropertyDef(
        "embedding", PropertyType.VECTOR, description="Semantic embedding vector for similarity search"
    ),
    PropertyDef("created_at", PropertyType.DATETIME, description="When the entity was ingested"),
    PropertyDef("updated_at", PropertyType.DATETIME, description="Last update timestamp"),
    PropertyDef("source_url", PropertyType.STRING, description="Source URL from Congress.gov"),
]

# Bill Node Type
BILL = NodeType(
    name="Bill",
    domain="congressional",
    schema_org_type="Legislation",
    description="A legislative bill introduced in Congress",
    properties=[
        *COMMON_PROPS,
        PropertyDef("number", PropertyType.STRING, required=True, indexed=True, description="Bill number (e.g., H.R.1234)"),
        PropertyDef("title", PropertyType.TEXT, required=True, fulltext=True, description="Bill title"),
        PropertyDef("short_title", PropertyType.STRING, description="Short title if available"),
        PropertyDef("congress", PropertyType.INTEGER, required=True, indexed=True, description="Congress number (e.g., 118)"),
        PropertyDef("chamber", PropertyType.STRING, indexed=True, description="House or Senate"),
        PropertyDef("bill_type", PropertyType.STRING, indexed=True, description="Type: hr, s, hjres, sjres, etc."),
        PropertyDef("introduced_date", PropertyType.DATE, indexed=True, description="Date introduced"),
        PropertyDef("latest_action_date", PropertyType.DATE, description="Date of most recent action"),
        PropertyDef("latest_action_text", PropertyType.TEXT, description="Text of most recent action"),
        PropertyDef("policy_area", PropertyType.STRING, indexed=True, description="Primary policy area"),
        PropertyDef("summary", PropertyType.TEXT, fulltext=True, description="Bill summary text"),
    ],
    mcp_tools=[
        MCPTool(
            name="get_bill",
            description="Get detailed information about a specific bill",
            cypher_template="MATCH (b:Bill {number: $number, congress: $congress}) RETURN b",
            parameters={"number": "string", "congress": "integer"},
        ),
        MCPTool(
            name="find_sponsors",
            description="Find all sponsors and cosponsors of a bill",
            cypher_template="""
                MATCH (m:Member)-[r:SPONSORS|COSPONSORS]->(b:Bill {number: $number, congress: $congress})
                RETURN m, type(r) as relationship
            """,
            parameters={"number": "string", "congress": "integer"},
        ),
        MCPTool(
            name="bill_history",
            description="Get the legislative history and actions for a bill",
            cypher_template="""
                MATCH (b:Bill {number: $number, congress: $congress})
                OPTIONAL MATCH (b)-[:HAS_ACTION]->(a:Action)
                RETURN b, collect(a) as actions ORDER BY a.date
            """,
            parameters={"number": "string", "congress": "integer"},
        ),
        MCPTool(
            name="related_bills",
            description="Find bills related to a given bill",
            cypher_template="""
                MATCH (b:Bill {number: $number, congress: $congress})-[:RELATED_TO]-(r:Bill)
                RETURN r
            """,
            parameters={"number": "string", "congress": "integer"},
        ),
        MCPTool(
            name="bills_by_policy",
            description="Find bills in a specific policy area",
            cypher_template="MATCH (b:Bill {policy_area: $policy_area, congress: $congress}) RETURN b LIMIT $limit",
            parameters={"policy_area": "string", "congress": "integer", "limit": "integer"},
        ),
    ],
)

# Member Node Type
MEMBER = NodeType(
    name="Member",
    domain="congressional",
    schema_org_type="Person",
    description="A member of Congress (Representative or Senator)",
    additional_labels=["Person"],
    properties=[
        *COMMON_PROPS,
        PropertyDef("bioguide_id", PropertyType.STRING, required=True, unique=True, indexed=True, description="Bioguide ID"),
        PropertyDef("name", PropertyType.STRING, required=True, fulltext=True, description="Full name"),
        PropertyDef("first_name", PropertyType.STRING, description="First name"),
        PropertyDef("last_name", PropertyType.STRING, indexed=True, description="Last name"),
        PropertyDef("party", PropertyType.STRING, indexed=True, description="Political party (D, R, I)"),
        PropertyDef("state", PropertyType.STRING, indexed=True, description="State represented"),
        PropertyDef("district", PropertyType.STRING, description="District number (House only)"),
        PropertyDef("chamber", PropertyType.STRING, indexed=True, description="House or Senate"),
        PropertyDef("terms_served", PropertyType.INTEGER, description="Number of terms served"),
        PropertyDef("current_term_start", PropertyType.DATE, description="Start of current term"),
        PropertyDef("current_term_end", PropertyType.DATE, description="End of current term"),
        PropertyDef("office_address", PropertyType.STRING, description="DC office address"),
        PropertyDef("phone", PropertyType.STRING, description="Office phone number"),
        PropertyDef("url", PropertyType.STRING, description="Official website URL"),
    ],
    mcp_tools=[
        MCPTool(
            name="get_member",
            description="Get detailed information about a specific member of Congress",
            cypher_template="MATCH (m:Member {bioguide_id: $bioguide_id}) RETURN m",
            parameters={"bioguide_id": "string"},
        ),
        MCPTool(
            name="member_bills",
            description="Find all bills sponsored by a member",
            cypher_template="""
                MATCH (m:Member {bioguide_id: $bioguide_id})-[:SPONSORS]->(b:Bill)
                RETURN b ORDER BY b.introduced_date DESC LIMIT $limit
            """,
            parameters={"bioguide_id": "string", "limit": "integer"},
        ),
        MCPTool(
            name="members_by_state",
            description="Find all members representing a state",
            cypher_template="MATCH (m:Member {state: $state}) RETURN m",
            parameters={"state": "string"},
        ),
        MCPTool(
            name="members_by_party",
            description="Find all members of a political party",
            cypher_template="MATCH (m:Member {party: $party}) RETURN m",
            parameters={"party": "string"},
        ),
        MCPTool(
            name="member_committees",
            description="Find all committees a member serves on",
            cypher_template="""
                MATCH (m:Member {bioguide_id: $bioguide_id})-[r:SERVES_ON]->(c:Committee)
                RETURN c, r.role as role
            """,
            parameters={"bioguide_id": "string"},
        ),
    ],
)

# Committee Node Type
COMMITTEE = NodeType(
    name="Committee",
    domain="congressional",
    schema_org_type="Organization",
    description="A congressional committee or subcommittee",
    additional_labels=["Organization"],
    properties=[
        *COMMON_PROPS,
        PropertyDef("system_code", PropertyType.STRING, required=True, unique=True, indexed=True, description="Committee system code"),
        PropertyDef("name", PropertyType.STRING, required=True, fulltext=True, description="Committee name"),
        PropertyDef("chamber", PropertyType.STRING, indexed=True, description="House, Senate, or Joint"),
        PropertyDef("committee_type", PropertyType.STRING, indexed=True, description="Standing, Select, Joint, etc."),
        PropertyDef("parent_committee", PropertyType.STRING, description="Parent committee code (for subcommittees)"),
        PropertyDef("jurisdiction", PropertyType.TEXT, description="Committee jurisdiction description"),
        PropertyDef("url", PropertyType.STRING, description="Committee website URL"),
    ],
    mcp_tools=[
        MCPTool(
            name="get_committee",
            description="Get detailed information about a committee",
            cypher_template="MATCH (c:Committee {system_code: $system_code}) RETURN c",
            parameters={"system_code": "string"},
        ),
        MCPTool(
            name="committee_members",
            description="Find all members serving on a committee",
            cypher_template="""
                MATCH (m:Member)-[r:SERVES_ON]->(c:Committee {system_code: $system_code})
                RETURN m, r.role as role
            """,
            parameters={"system_code": "string"},
        ),
        MCPTool(
            name="committee_bills",
            description="Find bills referred to a committee",
            cypher_template="""
                MATCH (b:Bill)-[:REFERRED_TO]->(c:Committee {system_code: $system_code})
                RETURN b ORDER BY b.introduced_date DESC LIMIT $limit
            """,
            parameters={"system_code": "string", "limit": "integer"},
        ),
        MCPTool(
            name="subcommittees",
            description="Find subcommittees of a committee",
            cypher_template="""
                MATCH (c:Committee {parent_committee: $system_code})
                RETURN c
            """,
            parameters={"system_code": "string"},
        ),
    ],
)

# ============================================================================
# Relationships
# ============================================================================

RELATIONSHIPS = [
    RelationshipType(
        name="SPONSORS",
        from_node="Member",
        to_node="Bill",
        description="Member is the primary sponsor of a bill",
        properties=[
            PropertyDef("date", PropertyType.DATE, description="Date of sponsorship"),
        ],
    ),
    RelationshipType(
        name="COSPONSORS",
        from_node="Member",
        to_node="Bill",
        description="Member is a cosponsor of a bill",
        properties=[
            PropertyDef("date", PropertyType.DATE, description="Date of cosponsorship"),
            PropertyDef("withdrawn", PropertyType.BOOLEAN, description="Whether cosponsorship was withdrawn"),
        ],
    ),
    RelationshipType(
        name="SERVES_ON",
        from_node="Member",
        to_node="Committee",
        description="Member serves on a committee",
        properties=[
            PropertyDef("role", PropertyType.STRING, description="Role (Chair, Ranking Member, Member)"),
            PropertyDef("start_date", PropertyType.DATE, description="Start of service"),
        ],
    ),
    RelationshipType(
        name="REFERRED_TO",
        from_node="Bill",
        to_node="Committee",
        description="Bill was referred to a committee",
        properties=[
            PropertyDef("date", PropertyType.DATE, description="Date of referral"),
        ],
    ),
    RelationshipType(
        name="RELATED_TO",
        from_node="Bill",
        to_node="Bill",
        description="Bills are related (companion, identical, etc.)",
        properties=[
            PropertyDef("relationship_type", PropertyType.STRING, description="Type of relationship"),
        ],
    ),
    RelationshipType(
        name="AMENDS",
        from_node="Bill",
        to_node="Bill",
        description="Bill amends another bill",
    ),
    RelationshipType(
        name="SUBCOMMITTEE_OF",
        from_node="Committee",
        to_node="Committee",
        description="Subcommittee belongs to parent committee",
    ),
]

# ============================================================================
# Ontology Registry
# ============================================================================

ONTOLOGY = {
    "nodes": {
        "Bill": BILL,
        "Member": MEMBER,
        "Committee": COMMITTEE,
    },
    "relationships": {rel.name: rel for rel in RELATIONSHIPS},
    "domain": "congressional",
    "version": "1.0.0",
}


def get_node_type(name: str) -> NodeType | None:
    """Get a node type by name."""
    return ONTOLOGY["nodes"].get(name)


def get_all_node_types() -> list[NodeType]:
    """Get all node types."""
    return list(ONTOLOGY["nodes"].values())


def get_all_relationship_types() -> list[RelationshipType]:
    """Get all relationship types."""
    return list(ONTOLOGY["relationships"].values())
