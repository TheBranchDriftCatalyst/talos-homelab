"""
SEC EDGAR Domain Entities

Pydantic models for Companies, Filings, and SEC Documents.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class Company(BaseModel):
    """SEC registered company entity."""

    # Identifiers
    cik: str = Field(description="Central Index Key (SEC identifier)")
    ticker: str | None = Field(default=None, description="Stock ticker symbol")

    # Info
    name: str = Field(description="Company name")
    sic: str | None = Field(default=None, description="Standard Industrial Classification code")
    sic_description: str | None = Field(default=None, description="SIC industry description")
    state: str | None = Field(default=None, description="State of incorporation")
    fiscal_year_end: str | None = Field(default=None, description="Fiscal year end (MMDD)")

    # Source
    source_url: str | None = Field(default=None, description="SEC EDGAR URL")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_submissions(cls, data: dict[str, Any], ticker: str | None = None) -> "Company":
        """Create Company from SEC submissions response."""
        return cls(
            cik=data.get("cik", ""),
            ticker=ticker,
            name=data.get("name", ""),
            sic=data.get("sic", ""),
            sic_description=data.get("sicDescription", ""),
            state=data.get("stateOfIncorporation", ""),
            fiscal_year_end=data.get("fiscalYearEnd", ""),
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={data.get('cik', '')}&type=10-K",
        )


class Filing(BaseModel):
    """SEC filing entity (10-K, 10-Q, 8-K, etc.)."""

    # Identifiers
    accession_number: str = Field(description="Unique filing accession number")
    cik: str = Field(description="Company CIK")

    # Filing info
    form_type: str = Field(description="Form type (10-K, 10-Q, 8-K, etc.)")
    filing_date: date | None = Field(default=None, description="Date filed with SEC")
    period_of_report: date | None = Field(default=None, description="Reporting period end date")

    # Company info (denormalized)
    company_name: str | None = Field(default=None, description="Company name")

    # Document info
    primary_document: str | None = Field(default=None, description="Primary document filename")
    document_url: str | None = Field(default=None, description="URL to filing document")

    # Source
    source_url: str | None = Field(default=None, description="SEC EDGAR filing URL")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Filing":
        """Create Filing from EDGAR API response."""
        filing_date = None
        if data.get("filing_date"):
            try:
                filing_date = date.fromisoformat(data["filing_date"])
            except (ValueError, TypeError):
                pass

        accession = data.get("accession_number", "")
        cik = data.get("cik", "")

        # Build URLs
        clean_accession = accession.replace("-", "")
        document_url = None
        if cik and accession and data.get("primary_document"):
            document_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{clean_accession}/{data['primary_document']}"

        return cls(
            accession_number=accession,
            cik=cik,
            form_type=data.get("form", ""),
            filing_date=filing_date,
            company_name=data.get("company_name"),
            primary_document=data.get("primary_document"),
            document_url=document_url,
            source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K",
        )


class SECDocument(BaseModel):
    """
    Parsed SEC document section.

    Represents a section from a 10-K filing (Item 1, Item 1A, Item 7, etc.)
    """

    # Identifiers
    id: str = Field(description="Unique document ID (accession-section)")
    filing_accession: str = Field(description="Parent filing accession number")

    # Section info
    section: str = Field(description="Section identifier (item_1, item_1a, item_7, etc.)")
    section_title: str = Field(description="Section title (e.g., 'Business')")

    # Content
    content: str = Field(description="Section text content")

    # Metadata
    cik: str | None = Field(default=None, description="Company CIK")
    company_name: str | None = Field(default=None, description="Company name")
    fiscal_year: int | None = Field(default=None, description="Fiscal year")

    # Source
    source_url: str | None = Field(default=None, description="URL to filing")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def text_length(self) -> int:
        """Get content length."""
        return len(self.content)


# Section mappings for 10-K filings
SECTION_10K_ITEMS = {
    "item_1": "Business",
    "item_1a": "Risk Factors",
    "item_1b": "Unresolved Staff Comments",
    "item_2": "Properties",
    "item_3": "Legal Proceedings",
    "item_4": "Mine Safety Disclosures",
    "item_5": "Market for Registrant's Common Equity",
    "item_6": "Selected Financial Data",
    "item_7": "Management's Discussion and Analysis",
    "item_7a": "Quantitative and Qualitative Disclosures About Market Risk",
    "item_8": "Financial Statements and Supplementary Data",
    "item_9": "Changes in and Disagreements With Accountants",
    "item_9a": "Controls and Procedures",
    "item_9b": "Other Information",
    "item_10": "Directors, Executive Officers and Corporate Governance",
    "item_11": "Executive Compensation",
    "item_12": "Security Ownership of Certain Beneficial Owners",
    "item_13": "Certain Relationships and Related Transactions",
    "item_14": "Principal Accounting Fees and Services",
    "item_15": "Exhibits, Financial Statement Schedules",
}
