"""
Congressional Domain Entities

Pydantic models for Bills, Members, and Committees.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class Bill(BaseModel):
    """Congressional bill entity."""

    # Identifiers
    id: str = Field(description="Unique identifier (e.g., 'hr1234-118')")
    number: str = Field(description="Bill number (e.g., 'H.R.1234')")
    congress: int = Field(description="Congress number (e.g., 118)")
    bill_type: str = Field(description="Bill type (hr, s, hjres, sjres, etc.)")

    # Content
    title: str = Field(description="Full bill title")
    short_title: str | None = Field(default=None, description="Short title if available")
    summary: str | None = Field(default=None, description="Bill summary")

    # Metadata
    chamber: str = Field(description="House or Senate")
    introduced_date: date | None = Field(default=None, description="Date introduced")
    latest_action_date: date | None = Field(default=None, description="Date of latest action")
    latest_action_text: str | None = Field(default=None, description="Text of latest action")
    policy_area: str | None = Field(default=None, description="Primary policy area")

    # Source
    source_url: str | None = Field(default=None, description="Congress.gov URL")
    api_url: str | None = Field(default=None, description="API URL")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_api_response(cls, data: dict[str, Any], congress: int) -> "Bill":
        """Create Bill from Congress.gov API response."""
        bill_type = data.get("type", "").lower()
        number = data.get("number", "")
        bill_number = f"{bill_type.upper()}.{number}" if bill_type else str(number)

        # Parse dates
        introduced_date = None
        if data.get("introducedDate"):
            try:
                introduced_date = date.fromisoformat(data["introducedDate"])
            except (ValueError, TypeError):
                pass

        latest_action_date = None
        latest_action = data.get("latestAction", {})
        if latest_action.get("actionDate"):
            try:
                latest_action_date = date.fromisoformat(latest_action["actionDate"])
            except (ValueError, TypeError):
                pass

        return cls(
            id=f"{bill_type}{number}-{congress}",
            number=bill_number,
            congress=congress,
            bill_type=bill_type,
            title=data.get("title", ""),
            short_title=data.get("shortTitle"),
            summary=None,  # Requires separate API call
            chamber=data.get("originChamber", ""),
            introduced_date=introduced_date,
            latest_action_date=latest_action_date,
            latest_action_text=latest_action.get("text"),
            policy_area=data.get("policyArea", {}).get("name"),
            source_url=data.get("url"),
            api_url=data.get("url"),
        )


class Member(BaseModel):
    """Congressional member entity."""

    # Identifiers
    id: str = Field(description="Bioguide ID")
    bioguide_id: str = Field(description="Bioguide ID")

    # Name
    name: str = Field(description="Full name")
    first_name: str | None = Field(default=None)
    last_name: str | None = Field(default=None)

    # Position
    party: str | None = Field(default=None, description="Political party (D, R, I)")
    state: str | None = Field(default=None, description="State code")
    district: str | None = Field(default=None, description="District number (House only)")
    chamber: str | None = Field(default=None, description="House or Senate")

    # Term info
    terms_served: int = Field(default=0, description="Number of terms served")
    current_term_start: date | None = Field(default=None)
    current_term_end: date | None = Field(default=None)

    # Contact
    office_address: str | None = Field(default=None)
    phone: str | None = Field(default=None)
    url: str | None = Field(default=None)

    # Source
    source_url: str | None = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Member":
        """Create Member from Congress.gov API response."""
        bioguide_id = data.get("bioguideId", "")

        # Parse current term
        terms = data.get("terms", {}).get("item", [])
        current_term = terms[-1] if terms else {}

        term_start = None
        term_end = None
        if current_term.get("startYear"):
            try:
                term_start = date(int(current_term["startYear"]), 1, 1)
            except (ValueError, TypeError):
                pass
        if current_term.get("endYear"):
            try:
                term_end = date(int(current_term["endYear"]), 12, 31)
            except (ValueError, TypeError):
                pass

        return cls(
            id=bioguide_id,
            bioguide_id=bioguide_id,
            name=data.get("name", ""),
            first_name=data.get("firstName"),
            last_name=data.get("lastName"),
            party=data.get("partyName", "")[:1] if data.get("partyName") else None,
            state=data.get("state"),
            district=data.get("district"),
            chamber=current_term.get("chamber"),
            terms_served=len(terms),
            current_term_start=term_start,
            current_term_end=term_end,
            url=data.get("url"),
            source_url=data.get("url"),
        )


class Committee(BaseModel):
    """Congressional committee entity."""

    # Identifiers
    id: str = Field(description="Committee system code")
    system_code: str = Field(description="Committee system code")

    # Info
    name: str = Field(description="Committee name")
    chamber: str | None = Field(default=None, description="House, Senate, or Joint")
    committee_type: str | None = Field(default=None, description="Standing, Select, etc.")
    parent_committee: str | None = Field(default=None, description="Parent committee code")

    # Details
    jurisdiction: str | None = Field(default=None, description="Committee jurisdiction")
    url: str | None = Field(default=None)

    # Source
    source_url: str | None = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Committee":
        """Create Committee from Congress.gov API response."""
        system_code = data.get("systemCode", "")

        return cls(
            id=system_code,
            system_code=system_code,
            name=data.get("name", ""),
            chamber=data.get("chamber"),
            committee_type=data.get("committeeTypeCode"),
            parent_committee=data.get("parent", {}).get("systemCode"),
            url=data.get("url"),
            source_url=data.get("url"),
        )
