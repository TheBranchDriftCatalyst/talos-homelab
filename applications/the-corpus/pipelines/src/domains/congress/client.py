"""
Congress.gov API Client

Rate-limited client for Congress.gov API v3.
Docs: https://api.congress.gov/
"""

from typing import Any, Iterator

from corpus_core.clients import BaseAPIClient
from corpus_core import get_env_str


class CongressAPIClient(BaseAPIClient):
    """
    Client for Congress.gov API.

    Rate limit: 5000 requests/hour (enforced by base class).
    """

    def __init__(
        self,
        api_key: str | None = None,
    ):
        api_key = api_key or get_env_str(
            "CONGRESS_API_KEY", "",
            description="Congress.gov API key (get from https://api.congress.gov/sign-up/)",
            domain="congress",
            required=True,
            secret=True,
        )
        if not api_key:
            raise ValueError("CONGRESS_API_KEY environment variable required")

        super().__init__(
            api_key=api_key,
            requests_per_hour=5000,
            timeout=30.0,
        )

    @property
    def base_url(self) -> str:
        return "https://api.congress.gov/v3"

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Api-Key": self.api_key or "",
        }

    def get_bills(
        self,
        congress: int = 118,
        limit: int = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get bills for a congress."""
        return self.get(
            f"/bill/{congress}",
            params={"limit": limit, "offset": offset},
        )

    def get_bill_detail(self, congress: int, bill_type: str, number: int) -> dict[str, Any]:
        """Get detailed information about a specific bill."""
        return self.get(f"/bill/{congress}/{bill_type}/{number}")

    def get_bill_sponsors(self, congress: int, bill_type: str, number: int) -> dict[str, Any]:
        """Get sponsors/cosponsors for a bill."""
        return self.get(f"/bill/{congress}/{bill_type}/{number}/cosponsors")

    def get_bill_actions(self, congress: int, bill_type: str, number: int) -> dict[str, Any]:
        """Get actions for a bill."""
        return self.get(f"/bill/{congress}/{bill_type}/{number}/actions")

    def iterate_bills(
        self,
        congress: int = 118,
        max_bills: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iterate through all bills for a congress."""
        count = 0
        for bill in self.paginate(
            f"/bill/{congress}",
            results_key="bills",
            page_size=250,
        ):
            yield bill
            count += 1
            if max_bills and count >= max_bills:
                break

    def get_members(
        self,
        congress: int = 118,
        limit: int = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get members for a congress."""
        return self.get(
            f"/member/congress/{congress}",
            params={"limit": limit, "offset": offset},
        )

    def get_member_detail(self, bioguide_id: str) -> dict[str, Any]:
        """Get detailed information about a member."""
        return self.get(f"/member/{bioguide_id}")

    def iterate_members(
        self,
        congress: int = 118,
        max_members: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iterate through all members for a congress."""
        count = 0
        for member in self.paginate(
            f"/member/congress/{congress}",
            results_key="members",
            page_size=250,
        ):
            yield member
            count += 1
            if max_members and count >= max_members:
                break

    def get_committees(
        self,
        congress: int = 118,
        chamber: str | None = None,
        limit: int = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get committees for a congress."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if chamber:
            params["chamber"] = chamber

        return self.get(f"/committee/{congress}", params=params)

    def get_committee_detail(self, congress: int, chamber: str, committee_code: str) -> dict[str, Any]:
        """Get detailed information about a committee."""
        return self.get(f"/committee/{congress}/{chamber}/{committee_code}")

    def iterate_committees(
        self,
        congress: int = 118,
        max_committees: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iterate through all committees for a congress."""
        count = 0
        for committee in self.paginate(
            f"/committee/{congress}",
            results_key="committees",
            page_size=250,
        ):
            yield committee
            count += 1
            if max_committees and count >= max_committees:
                break
