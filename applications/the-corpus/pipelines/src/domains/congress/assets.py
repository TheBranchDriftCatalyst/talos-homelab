"""
Congressional Domain Dagster Assets

ETL pipeline assets for Congress.gov data:
1. Raw data extraction (bills, members, committees)
2. Document transformation for NER training
"""

import os
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    MetadataValue,
    Output,
    asset,
)

from corpus_core.models import Document

from .client import CongressAPIClient
from .entities import Bill, Member, Committee


# ============================================================================
# Raw Data Extraction Assets
# ============================================================================

@asset(
    group_name="congress",
    description="Extract bills from Congress.gov",
    compute_kind="extract",
)
def congress_bills(context: AssetExecutionContext) -> Output[list[Bill]]:
    """
    Extract bills from Congress.gov.

    Fetches bills from the current congress with pagination.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_bills = int(os.environ.get("MAX_BILLS", "1000"))

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
    group_name="congress",
    description="Extract members from Congress.gov",
    compute_kind="extract",
)
def congress_members(context: AssetExecutionContext) -> Output[list[Member]]:
    """
    Extract members from Congress.gov.

    Fetches all members of the current congress.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_members = int(os.environ.get("MAX_MEMBERS", "600"))

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
    group_name="congress",
    description="Extract committees from Congress.gov",
    compute_kind="extract",
)
def congress_committees(context: AssetExecutionContext) -> Output[list[Committee]]:
    """
    Extract committees from Congress.gov.

    Fetches all committees of the current congress.
    """
    congress = int(os.environ.get("CONGRESS_NUMBER", "118"))
    max_committees = int(os.environ.get("MAX_COMMITTEES", "300"))

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
    group_name="congress",
    description="Transform raw data into training documents",
    compute_kind="transform",
)
def congress_documents(
    context: AssetExecutionContext,
    congress_bills: list[Bill],
    congress_members: list[Member],
    congress_committees: list[Committee],
) -> Output[list[Document]]:
    """
    Transform raw congressional data into training documents.

    Creates documents suitable for NER training data preparation.
    """
    documents = []

    # Transform bills
    for bill in congress_bills:
        doc = Document(
            id=f"congress-bill-{bill.id}",
            title=bill.title,
            content=f"Bill {bill.number} ({bill.chamber}). {bill.summary or ''}",
            source="congress.gov",
            source_url=bill.source_url,
            document_type="bill",
            domain="congress",
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
        doc = Document(
            id=f"congress-member-{member.bioguide_id}",
            title=member.name,
            content=f"{member.name}, {member.party or 'Unknown'} party, representing {member.state or 'Unknown'}",
            source="congress.gov",
            source_url=member.source_url,
            document_type="member_profile",
            domain="congress",
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
        doc = Document(
            id=f"congress-committee-{committee.system_code}",
            title=committee.name,
            content=f"{committee.name} ({committee.chamber or 'Unknown'} {committee.committee_type or 'committee'})",
            source="congress.gov",
            source_url=committee.source_url,
            document_type="committee_profile",
            domain="congress",
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

    context.log.info(f"Created {len(documents)} training documents")

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
