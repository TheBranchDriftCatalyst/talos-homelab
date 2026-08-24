"""Monitor Mode - Page change detection.

Watches pages for changes and triggers alerts/actions.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Callable, TYPE_CHECKING

from .base import AgentMode

if TYPE_CHECKING:
    from ..server import UIServer

logger = logging.getLogger(__name__)


@dataclass
class WatchedPage:
    """A page being monitored for changes."""
    url: str
    name: str = ""
    check_interval_seconds: int = 300  # 5 minutes default
    last_check: Optional[datetime] = None
    last_hash: Optional[str] = None
    selector: Optional[str] = None  # CSS selector to watch (None = whole page)
    on_change: Optional[Callable] = None  # Callback when change detected


@dataclass
class PageChange:
    """Detected page change."""
    url: str
    name: str
    detected_at: datetime
    old_hash: str
    new_hash: str
    content_preview: str = ""


class MonitorMode(AgentMode):
    """Page monitoring and change detection mode.

    Workflow:
    1. Load list of pages to monitor
    2. Periodically check each page
    3. Detect changes using content hashing
    4. Optionally use Reasoner to analyze changes
    5. Trigger alerts/callbacks

    Uses:
    - Navigator: Load pages and extract content
    - Reasoner (optional): Analyze what changed
    """

    MODE_NAME = "monitor"
    MODE_DESCRIPTION = "Monitor pages for changes"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watched_pages: List[WatchedPage] = []
        self.changes: List[PageChange] = []

    @property
    def uses_reasoner(self) -> bool:
        """Monitor can optionally use reasoner for change analysis."""
        return False  # Optional - enable if analyzing changes

    def add_watch(
        self,
        url: str,
        name: str = "",
        interval: int = 300,
        selector: Optional[str] = None,
        on_change: Optional[Callable] = None,
    ):
        """Add a page to monitor.

        Args:
            url: Page URL to monitor
            name: Friendly name for the page
            interval: Check interval in seconds
            selector: CSS selector to watch (None = whole page)
            on_change: Callback function when change detected
        """
        self.watched_pages.append(WatchedPage(
            url=url,
            name=name or url,
            check_interval_seconds=interval,
            selector=selector,
            on_change=on_change,
        ))
        logger.info(f"Added watch: {name or url}")

    def remove_watch(self, url: str):
        """Remove a page from monitoring."""
        self.watched_pages = [p for p in self.watched_pages if p.url != url]

    async def check_page(self, page_config: WatchedPage) -> Optional[PageChange]:
        """Check a single page for changes.

        Returns:
            PageChange if change detected, None otherwise
        """
        # TODO: Implement page checking
        # 1. Navigate to page
        # 2. Extract content (full page or selector)
        # 3. Hash content
        # 4. Compare to last hash
        # 5. Return change if different

        await self._log("warning", "MonitorMode.check_page is a stub")
        return None

    async def run_session(self) -> bool:
        """Run a monitoring check cycle."""
        await self._update_status("monitoring")
        await self._log("info", "MonitorMode session started")

        if not self.watched_pages:
            await self._log("warning", "No pages configured to monitor")
            await self._update_status("idle")
            return False

        # TODO: Implement monitoring cycle
        # For now, just log that it's a stub

        await self._log("warning", "MonitorMode is a stub - implement run_session()")
        await self._update_status("idle")

        return False

    def get_session_delay(self) -> float:
        """Monitor mode uses shorter intervals."""
        # Find minimum interval from watched pages
        if self.watched_pages:
            return min(p.check_interval_seconds for p in self.watched_pages)
        return 60  # Default 1 minute
