"""
Base API Client

Generic rate-limited HTTP client with retry logic.
Extend for domain-specific API clients.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger()

T = TypeVar("T")


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, requests_per_hour: int):
        self.requests_per_hour = requests_per_hour
        self.tokens = requests_per_hour
        self.last_refill = time.monotonic()
        self.refill_rate = requests_per_hour / 3600  # tokens per second

    def acquire(self) -> None:
        """Acquire a token, blocking if necessary."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.requests_per_hour, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.refill_rate
            logger.info("rate_limit_waiting", wait_seconds=wait_time)
            time.sleep(wait_time)
            self.tokens = 1

        self.tokens -= 1


class BaseAPIClient(ABC):
    """
    Base class for rate-limited API clients.

    Subclasses should implement:
    - base_url property
    - default_headers property (optional)
    - transform_response method (optional)
    """

    def __init__(
        self,
        api_key: str | None = None,
        requests_per_hour: int = 5000,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(requests_per_hour)
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the base URL for the API."""
        ...

    @property
    def default_headers(self) -> dict[str, str]:
        """Return default headers for requests."""
        return {}

    def get_client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=self.default_headers,
                timeout=self.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "BaseAPIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
    )
    def _make_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with rate limiting and retries."""
        self.rate_limiter.acquire()

        client = self.get_client()
        logger.debug("api_request", method=method, path=path, params=params)

        response = client.request(method, path, params=params, json=json)

        # Retry on rate limit (429) and server errors (5xx)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning("rate_limited", retry_after=retry_after)
            time.sleep(retry_after)
            response.raise_for_status()
        elif response.status_code >= 500:
            response.raise_for_status()

        return response

    def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a GET request and return JSON response."""
        response = self._make_request("GET", path, params=params)
        response.raise_for_status()
        return response.json()

    def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a POST request and return JSON response."""
        response = self._make_request("POST", path, json=json)
        response.raise_for_status()
        return response.json()

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_key: str = "offset",
        page_size: int = 250,
        max_pages: int | None = None,
        results_key: str | None = None,
    ):
        """
        Paginate through API results.

        Yields individual items from paginated responses.
        """
        params = params or {}
        page = 0
        total_yielded = 0

        while max_pages is None or page < max_pages:
            params[page_key] = page * page_size
            params["limit"] = page_size

            response = self.get(path, params)

            # Extract results from response
            if results_key:
                items = response.get(results_key, [])
            elif isinstance(response, list):
                items = response
            else:
                # Try common keys
                for key in ["results", "data", "items", "bills", "members", "committees"]:
                    if key in response:
                        items = response[key]
                        break
                else:
                    items = [response]

            if not items:
                break

            for item in items:
                yield item
                total_yielded += 1

            # Check if we've reached the end
            if len(items) < page_size:
                break

            page += 1

        logger.info("pagination_complete", total_items=total_yielded, pages=page + 1)
