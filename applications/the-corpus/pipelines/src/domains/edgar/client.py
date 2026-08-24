"""
SEC EDGAR API Client

Rate-limited client for SEC EDGAR data.
Docs: https://www.sec.gov/developer

Note: No API key required, but rate limit of 10 requests/second.
"""

import re
from typing import Any, Iterator

from corpus_core.clients import BaseAPIClient


class EDGARClient(BaseAPIClient):
    """
    Client for SEC EDGAR API.

    Rate limit: 10 requests/second (36000/hour).
    No authentication required.
    """

    def __init__(self):
        super().__init__(
            api_key=None,
            requests_per_hour=36000,  # ~10 req/sec
            timeout=60.0,
        )

    @property
    def base_url(self) -> str:
        return "https://data.sec.gov"

    @property
    def default_headers(self) -> dict[str, str]:
        # SEC requires a User-Agent header
        return {
            "Accept": "application/json",
            "User-Agent": "corpus-pipelines/0.1.0 (NER training data collection)",
        }

    def _pad_cik(self, cik: str) -> str:
        """Pad CIK to 10 digits."""
        return cik.zfill(10)

    def get_company_submissions(self, cik: str) -> dict[str, Any]:
        """
        Get all filings for a company.

        Args:
            cik: Central Index Key (company identifier)

        Returns:
            Company info and list of filings
        """
        padded_cik = self._pad_cik(cik)
        return self.get(f"/submissions/CIK{padded_cik}.json")

    def get_company_facts(self, cik: str) -> dict[str, Any]:
        """
        Get XBRL facts for a company.

        Useful for extracting structured financial data.
        """
        padded_cik = self._pad_cik(cik)
        return self.get(f"/api/xbrl/companyfacts/CIK{padded_cik}.json")

    def get_filing_index(self, cik: str, accession_number: str) -> dict[str, Any]:
        """
        Get the filing index (list of documents in a filing).

        Args:
            cik: Company CIK
            accession_number: Filing accession number (format: 0001234567-24-000001)

        Returns:
            Index of filing documents
        """
        padded_cik = self._pad_cik(cik)
        # Convert accession format: 0001234567-24-000001 -> 000123456724000001
        clean_accession = accession_number.replace("-", "")
        return self.get(f"/cik{padded_cik}/{clean_accession}/index.json")

    def get_filing_document(self, cik: str, accession_number: str, filename: str) -> str:
        """
        Download a filing document (HTML/XML).

        Args:
            cik: Company CIK
            accession_number: Filing accession number
            filename: Document filename (e.g., 'form10k.htm')

        Returns:
            Document content as text
        """
        padded_cik = self._pad_cik(cik)
        clean_accession = accession_number.replace("-", "")
        path = f"/Archives/edgar/data/{padded_cik}/{clean_accession}/{filename}"
        return self.get_text(path)

    def iterate_10k_filings(
        self,
        cik: str,
        max_filings: int | None = 5,
    ) -> Iterator[dict[str, Any]]:
        """
        Iterate through 10-K filings for a company.

        Args:
            cik: Company CIK
            max_filings: Maximum number of filings to return

        Yields:
            Filing metadata dicts
        """
        submissions = self.get_company_submissions(cik)

        filings = submissions.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])

        count = 0
        for i, form in enumerate(forms):
            if form in ("10-K", "10-K/A"):  # Include amendments
                yield {
                    "form": form,
                    "accession_number": accessions[i] if i < len(accessions) else None,
                    "filing_date": dates[i] if i < len(dates) else None,
                    "primary_document": primary_docs[i] if i < len(primary_docs) else None,
                    "cik": cik,
                    "company_name": submissions.get("name", ""),
                }
                count += 1
                if max_filings and count >= max_filings:
                    break


# S&P 500 CIKs (subset for MVP - full list would be loaded from file)
SP500_CIKS = {
    "AAPL": "320193",
    "MSFT": "789019",
    "AMZN": "1018724",
    "GOOGL": "1652044",
    "META": "1326801",
    "NVDA": "1045810",
    "TSLA": "1318605",
    "BRK.B": "1067983",
    "JPM": "19617",
    "JNJ": "200406",
    "V": "1403161",
    "PG": "80424",
    "UNH": "731766",
    "HD": "354950",
    "MA": "1141391",
    "DIS": "1744489",
    "PYPL": "1633917",
    "NFLX": "1065280",
    "ADBE": "796343",
    "CRM": "1108524",
}
