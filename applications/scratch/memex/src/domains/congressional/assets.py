"""
Congressional Domain Dagster Assets

ETL pipeline assets for Congress.gov data:
1. Raw data extraction (bills, members, committees)
2. Document transformation
3. Entity extraction via LLM
4. Knowledge graph loading
"""

import os
from typing import Any

from dagster import (
    AssetExecutionContext,
    MetadataValue,
    Output,
    asset,
)

from shared.models.document import LLMDocument
from shared.models.entity import ExtractedEntity
from shared.base_entity_extractor import BaseEntityExtractor
from shared.base_graph_loader import BaseGraphLoader
from shared.embedding_service import EmbeddingService

from .client import CongressAPIClient
from .entities import Bill, Member, Committee


# ============================================================================
# Raw Data Extraction Assets
# ============================================================================

@asset(
    group_name="congressional",
    description="Extract bills from Congress.gov API",
    compute_kind="api",
)
def congress_bills(context: AssetExecutionContext) -> Output[list[Bill]]:
    """
    Extract bills from Congress.gov API.

    Fetches bills from the current congress with pagination.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_bills = int(os.environ.get("MAX_BILLS", "100"))  # Limit for dev

    with CongressAPIClient() as client:
        bills = []
        for bill_data in client.iterate_bills(congress=congress, max_bills=max_bills):
            bill = Bill.from_api_response(bill_data, congress)
            bills.append(bill)

        context.log.info(f"Extracted {len(bills)} bills from congress {congress}")

    return Output(
        bills,
        metadata={
            "congress": congress,
            "count": len(bills),
            "sample_titles": MetadataValue.json([b.title[:100] for b in bills[:5]]),
        },
    )


@asset(
    group_name="congressional",
    description="Extract members from Congress.gov API",
    compute_kind="api",
)
def congress_members(context: AssetExecutionContext) -> Output[list[Member]]:
    """
    Extract members from Congress.gov API.

    Fetches all members of the current congress.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_members = int(os.environ.get("MAX_MEMBERS", "100"))

    with CongressAPIClient() as client:
        members = []
        for member_data in client.iterate_members(congress=congress, max_members=max_members):
            member = Member.from_api_response(member_data)
            members.append(member)

        context.log.info(f"Extracted {len(members)} members from congress {congress}")

    return Output(
        members,
        metadata={
            "congress": congress,
            "count": len(members),
            "by_party": MetadataValue.json({
                "D": len([m for m in members if m.party == "D"]),
                "R": len([m for m in members if m.party == "R"]),
                "I": len([m for m in members if m.party == "I"]),
            }),
        },
    )


@asset(
    group_name="congressional",
    description="Extract committees from Congress.gov API",
    compute_kind="api",
)
def congress_committees(context: AssetExecutionContext) -> Output[list[Committee]]:
    """
    Extract committees from Congress.gov API.

    Fetches all committees of the current congress.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_committees = int(os.environ.get("MAX_COMMITTEES", "100"))

    with CongressAPIClient() as client:
        committees = []
        for committee_data in client.iterate_committees(congress=congress, max_committees=max_committees):
            committee = Committee.from_api_response(committee_data)
            committees.append(committee)

        context.log.info(f"Extracted {len(committees)} committees from congress {congress}")

    return Output(
        committees,
        metadata={
            "congress": congress,
            "count": len(committees),
            "by_chamber": MetadataValue.json({
                "House": len([c for c in committees if c.chamber == "House"]),
                "Senate": len([c for c in committees if c.chamber == "Senate"]),
                "Joint": len([c for c in committees if c.chamber == "Joint"]),
            }),
        },
    )


# ============================================================================
# Document Transformation Asset
# ============================================================================

@asset(
    group_name="congressional",
    description="Transform raw data into LLM documents",
    compute_kind="transform",
    deps=[congress_bills, congress_members, congress_committees],
)
def congress_documents(
    context: AssetExecutionContext,
    congress_bills: list[Bill],
    congress_members: list[Member],
    congress_committees: list[Committee],
) -> Output[list[LLMDocument]]:
    """
    Transform raw congressional data into LLM documents.

    Creates documents suitable for entity extraction.
    """
    documents = []

    # Transform bills
    for bill in congress_bills:
        doc = LLMDocument(
            id=f"bill-{bill.id}",
            title=bill.title,
            content=f"Bill {bill.number} ({bill.chamber}). {bill.summary or ''}",
            source="congress.gov",
            source_url=bill.source_url,
            document_type="bill",
            domain="congressional",
            entity_type="Bill",
            metadata={
                "congress": bill.congress,
                "bill_type": bill.bill_type,
                "chamber": bill.chamber,
                "policy_area": bill.policy_area,
            },
            sections={
                "latest_action": bill.latest_action_text or "",
            },
        )
        documents.append(doc)

    # Transform members
    for member in congress_members:
        doc = LLMDocument(
            id=f"member-{member.bioguide_id}",
            title=member.name,
            content=f"{member.name}, {member.party or 'Unknown'} party, representing {member.state or 'Unknown'}",
            source="congress.gov",
            source_url=member.source_url,
            document_type="member_profile",
            domain="congressional",
            entity_type="Member",
            metadata={
                "bioguide_id": member.bioguide_id,
                "party": member.party,
                "state": member.state,
                "chamber": member.chamber,
            },
        )
        documents.append(doc)

    # Transform committees
    for committee in congress_committees:
        doc = LLMDocument(
            id=f"committee-{committee.system_code}",
            title=committee.name,
            content=f"{committee.name} ({committee.chamber or 'Unknown'} {committee.committee_type or 'committee'})",
            source="congress.gov",
            source_url=committee.source_url,
            document_type="committee_profile",
            domain="congressional",
            entity_type="Committee",
            metadata={
                "system_code": committee.system_code,
                "chamber": committee.chamber,
                "committee_type": committee.committee_type,
            },
            sections={
                "jurisdiction": committee.jurisdiction or "",
            },
        )
        documents.append(doc)

    context.log.info(f"Created {len(documents)} LLM documents")

    return Output(
        documents,
        metadata={
            "total_documents": len(documents),
            "by_type": MetadataValue.json({
                "bills": len(congress_bills),
                "members": len(congress_members),
                "committees": len(congress_committees),
            }),
        },
    )


# ============================================================================
# Entity Extraction Asset
# ============================================================================

@asset(
    group_name="congressional",
    description="Extract entities from documents using LLM",
    compute_kind="llm",
    tags={
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"cpu": "500m", "memory": "1Gi"},
                }
            }
        }
    },
)
def congress_entities(
    context: AssetExecutionContext,
    congress_documents: list[LLMDocument],
) -> Output[list[ExtractedEntity]]:
    """
    Extract entities from documents using LLM-powered NER.

    Uses Ollama for entity extraction with schema-guided prompts.
    Entities are annotated with JSON-LD schemas for MCP discovery.
    """
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    extractor = BaseEntityExtractor(
        ollama_url=ollama_url,
        model="llama3.2",
    )

    all_entities = []

    for doc in congress_documents:
        try:
            # Extract entities from document
            text = doc.get_text_for_extraction()
            entities = extractor.extract_from_text_sync(text)

            # Add document reference to each entity
            for entity in entities:
                entity.properties["source_document_id"] = doc.id

            all_entities.extend(entities)
            context.log.debug(f"Extracted {len(entities)} entities from {doc.id}")

        except Exception as e:
            context.log.warning(f"Failed to extract from {doc.id}: {e}")

    context.log.info(f"Extracted {len(all_entities)} total entities")

    return Output(
        all_entities,
        metadata={
            "total_entities": len(all_entities),
            "by_type": MetadataValue.json({
                entity_type: len([e for e in all_entities if e.entity_type == entity_type])
                for entity_type in set(e.entity_type for e in all_entities)
            }),
            "avg_confidence": sum(e.confidence for e in all_entities) / len(all_entities) if all_entities else 0,
        },
    )


# ============================================================================
# Knowledge Graph Loading Asset
# ============================================================================

@asset(
    group_name="congressional",
    description="Load entities into Neo4j knowledge graph",
    compute_kind="graph",
    tags={
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"cpu": "200m", "memory": "512Mi"},
                }
            }
        }
    },
)
def congress_graph(
    context: AssetExecutionContext,
    congress_entities: list[ExtractedEntity],
) -> Output[dict[str, Any]]:
    """
    Load extracted entities into Neo4j knowledge graph.

    Creates nodes with:
    - JSON-LD schema annotations for MCP discovery
    - Vector embeddings for semantic search
    - Relationships between entities
    """
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "neo4j-password")
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    # Initialize services
    embedding_service = EmbeddingService(ollama_url=ollama_url)

    with BaseGraphLoader(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        embedding_service=embedding_service,
    ) as loader:
        loaded_ids = []
        relationship_count = 0

        for entity in congress_entities:
            try:
                entity_id = loader.load_entity_with_relationships(entity)
                if entity_id:
                    loaded_ids.append(entity_id)
                    relationship_count += len(entity.relationships)
            except Exception as e:
                context.log.warning(f"Failed to load entity {entity.id}: {e}")

        context.log.info(f"Loaded {len(loaded_ids)} entities with {relationship_count} relationships")

    return Output(
        {
            "loaded_count": len(loaded_ids),
            "relationship_count": relationship_count,
            "loaded_ids": loaded_ids[:100],  # Sample
        },
        metadata={
            "loaded_entities": len(loaded_ids),
            "relationships_created": relationship_count,
            "neo4j_uri": neo4j_uri,
        },
    )
