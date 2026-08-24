"""
SEC EDGAR domain.

ETL pipeline for financial filings:
- Companies (S&P 500)
- 10-K Filings
- Filing sections (Item 1, 1A, 7, etc.)
"""

from domains.edgar.entities import Company, Filing, SECDocument

__all__ = ["Company", "Filing", "SECDocument"]
