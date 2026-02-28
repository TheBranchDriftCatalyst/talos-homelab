"""Researcher Mode - Information extraction and research.

Uses Navigator (small model) to browse + Reasoner (large model) to extract data.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .base import AgentMode

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)


class ResearcherMode(AgentMode):
    """Research and data extraction mode.

    Workflow:
    1. Generate search queries for research goal (Reasoner)
    2. Navigate to search results (Navigator)
    3. Extract relevant data from pages (Reasoner)
    4. Compile findings

    Uses both models:
    - Navigator: Browse and navigate pages
    - Reasoner: Understand content, extract structured data
    """

    MODE_NAME = "researcher"
    MODE_DESCRIPTION = "Research and extract information from the web"

    @property
    def uses_reasoner(self) -> bool:
        """Researcher needs the reasoning model."""
        return True

    async def research(
        self,
        query: str,
        max_pages: int = 5,
        extract_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a research task.

        Args:
            query: Research query/goal
            max_pages: Maximum pages to visit
            extract_schema: Optional schema for data extraction

        Returns:
            Research results with extracted data
        """
        await self._log("info", f"Researching: {query}")

        results = {
            "query": query,
            "pages_visited": [],
            "findings": [],
            "extracted_data": [],
            "summary": "",
        }

        # TODO: Implement full research workflow
        # 1. Generate search queries
        # 2. Navigate to results
        # 3. Extract data from each page
        # 4. Compile findings

        await self._log("warning", "ResearcherMode is a stub - not yet implemented")
        return results

    async def run_session(self) -> bool:
        """Run a single research session."""
        await self._update_status("planning")
        await self._log("info", "ResearcherMode session started")

        # TODO: Implement research session
        # For now, just log that it's a stub

        await self._log("warning", "ResearcherMode is a stub - implement run_session()")
        await self._update_status("idle")

        # Return False since we didn't actually do anything
        return False
