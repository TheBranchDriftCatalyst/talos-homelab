"""
SEC EDGAR Domain Dagster Assets

ETL pipeline assets for SEC EDGAR data:
1. Company extraction (S&P 500 subset)
2. 10-K filing extraction
3. Document section parsing
"""

import os
import re
from html import unescape

from dagster import (
    AssetExecutionContext,
    MetadataValue,
    Output,
    asset,
)

from corpus_core.models import Document

from .client import EDGARClient, SP500_CIKS
from .entities import Company, Filing, SECDocument, SECTION_10K_ITEMS


# ============================================================================
# Raw Data Extraction Assets
# ============================================================================

@asset(
    group_name="edgar",
    description="Extract S&P 500 company information from SEC EDGAR",
    compute_kind="extract",
)
def edgar_companies(context: AssetExecutionContext) -> Output[list[Company]]:
    """
    Extract company information from SEC EDGAR.

    Uses a subset of S&P 500 companies for MVP.
    """
    max_companies = int(os.environ.get("MAX_COMPANIES", "20"))

    client = EDGARClient()
    companies = []

    for ticker, cik in list(SP500_CIKS.items())[:max_companies]:
        try:
            submissions = client.get_company_submissions(cik)
            company = Company.from_submissions(submissions, ticker=ticker)
            companies.append(company)
            context.log.info(f"Extracted company: {company.name} ({ticker})")
        except Exception as e:
            context.log.warning(f"Failed to extract {ticker}: {e}")

    context.log.info(f"Extracted {len(companies)} companies")

    return Output(
        companies,
        metadata={
            "count": len(companies),
            "tickers": MetadataValue.json([c.ticker for c in companies]),
        },
    )


@asset(
    group_name="edgar",
    description="Extract 10-K filings from SEC EDGAR",
    compute_kind="extract",
)
def edgar_filings(
    context: AssetExecutionContext,
    edgar_companies: list[Company],
) -> Output[list[Filing]]:
    """
    Extract 10-K filings for each company.

    Fetches last 5 years of 10-K filings per company.
    """
    max_filings_per_company = int(os.environ.get("MAX_FILINGS_PER_COMPANY", "5"))

    client = EDGARClient()
    filings = []

    for company in edgar_companies:
        try:
            for filing_data in client.iterate_10k_filings(
                cik=company.cik,
                max_filings=max_filings_per_company,
            ):
                filing = Filing.from_api_response(filing_data)
                filings.append(filing)

            context.log.info(f"Extracted filings for {company.name}")
        except Exception as e:
            context.log.warning(f"Failed to extract filings for {company.name}: {e}")

    context.log.info(f"Extracted {len(filings)} total filings")

    return Output(
        filings,
        metadata={
            "count": len(filings),
            "by_company": MetadataValue.json({
                c.name: len([f for f in filings if f.cik == c.cik])
                for c in edgar_companies
            }),
        },
    )


@asset(
    group_name="edgar",
    description="Parse 10-K filings into sections",
    compute_kind="transform",
)
def edgar_sections(
    context: AssetExecutionContext,
    edgar_filings: list[Filing],
) -> Output[list[SECDocument]]:
    """
    Parse 10-K filings into individual sections.

    Extracts key sections: Item 1 (Business), Item 1A (Risk Factors),
    Item 7 (MD&A), etc.
    """
    max_filings_to_parse = int(os.environ.get("MAX_FILINGS_TO_PARSE", "20"))

    client = EDGARClient()
    documents = []

    # Only process subset of filings (full parsing is expensive)
    for filing in edgar_filings[:max_filings_to_parse]:
        if not filing.primary_document or not filing.accession_number:
            continue

        try:
            # Download the filing HTML
            html_content = client.get_filing_document(
                cik=filing.cik,
                accession_number=filing.accession_number,
                filename=filing.primary_document,
            )

            # Parse sections from HTML
            sections = _parse_10k_sections(html_content)

            for section_id, content in sections.items():
                if len(content) < 100:  # Skip very short sections
                    continue

                section_title = SECTION_10K_ITEMS.get(section_id, section_id)

                doc = SECDocument(
                    id=f"{filing.accession_number}-{section_id}",
                    filing_accession=filing.accession_number,
                    section=section_id,
                    section_title=section_title,
                    content=content[:50000],  # Truncate very long sections
                    cik=filing.cik,
                    company_name=filing.company_name,
                    fiscal_year=filing.filing_date.year if filing.filing_date else None,
                    source_url=filing.document_url,
                )
                documents.append(doc)

            context.log.info(f"Parsed {len(sections)} sections from {filing.accession_number}")

        except Exception as e:
            context.log.warning(f"Failed to parse {filing.accession_number}: {e}")

    context.log.info(f"Extracted {len(documents)} document sections")

    return Output(
        documents,
        metadata={
            "count": len(documents),
            "by_section": MetadataValue.json({
                section: len([d for d in documents if d.section == section])
                for section in set(d.section for d in documents)
            }),
        },
    )


def _parse_10k_sections(html: str) -> dict[str, str]:
    """
    Parse 10-K HTML into sections.

    This is a simplified parser - production would use more sophisticated
    techniques (e.g., SEC-EDGAR-tools, sec-api, or ML-based extraction).
    """
    sections = {}

    # Remove HTML tags but keep text
    text = re.sub(r'<[^>]+>', ' ', html)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text)

    # Look for section headers
    # Pattern: "Item 1." or "ITEM 1" followed by section title
    item_pattern = r'(?:item|ITEM)\s*(\d+[aAbB]?)[\.\s]+'

    matches = list(re.finditer(item_pattern, text))

    for i, match in enumerate(matches):
        item_num = match.group(1).lower()
        section_key = f"item_{item_num}"

        # Get content until next section or end
        start = match.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = min(start + 100000, len(text))  # Max 100k chars

        content = text[start:end].strip()

        # Only keep if we have meaningful content
        if len(content) > 500 and section_key in SECTION_10K_ITEMS:
            sections[section_key] = content

    return sections


# ============================================================================
# Document Transformation Asset
# ============================================================================

@asset(
    group_name="edgar",
    description="Transform EDGAR data into training documents",
    compute_kind="transform",
)
def edgar_documents(
    context: AssetExecutionContext,
    edgar_companies: list[Company],
    edgar_sections: list[SECDocument],
) -> Output[list[Document]]:
    """
    Transform EDGAR data into training documents.

    Creates documents suitable for NER training focusing on:
    - Financial entities (ORG, MONEY, PERCENT)
    - Legal entities
    - Risk factors
    """
    documents = []

    # Create company lookup
    company_lookup = {c.cik: c for c in edgar_companies}

    # Transform sections into training documents
    for section in edgar_sections:
        company = company_lookup.get(section.cik)

        doc = Document(
            id=f"edgar-{section.id}",
            title=f"{section.company_name or 'Unknown'} - {section.section_title}",
            content=section.content,
            source="sec.gov",
            source_url=section.source_url,
            document_type="10k_section",
            domain="edgar",
            entity_type="SECDocument",
            metadata={
                "cik": section.cik,
                "company_name": section.company_name,
                "ticker": company.ticker if company else None,
                "section": section.section,
                "section_title": section.section_title,
                "fiscal_year": section.fiscal_year,
                "sic": company.sic if company else None,
                "industry": company.sic_description if company else None,
            },
            sections={
                section.section: section.content[:5000],  # Preview
            },
        )
        documents.append(doc)

    context.log.info(f"Created {len(documents)} training documents")

    return Output(
        documents,
        metadata={
            "total_documents": len(documents),
            "avg_content_length": sum(len(d.content) for d in documents) // max(len(documents), 1),
            "by_section": MetadataValue.json({
                section: len([d for d in documents if d.metadata.get("section") == section])
                for section in set(d.metadata.get("section") for d in documents)
            }),
        },
    )
