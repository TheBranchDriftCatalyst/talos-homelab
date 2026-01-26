"""
Shared utilities for corpus-core.

Provides common patterns used across domains:
- Date/datetime parsing
- Environment variable handling
- Base entity mixins
"""

import os
from datetime import date, datetime
from typing import TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ============================================================================
# Date Parsing Utilities
# ============================================================================

def parse_date(value: str | None) -> date | None:
    """
    Safely parse an ISO date string.

    Args:
        value: ISO date string (YYYY-MM-DD) or None

    Returns:
        Parsed date or None if invalid/empty
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_datetime(value: str | None) -> datetime | None:
    """
    Safely parse an ISO datetime string.

    Args:
        value: ISO datetime string or None

    Returns:
        Parsed datetime or None if invalid/empty
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_timestamp(value: int | float | None) -> datetime | None:
    """
    Safely parse a Unix timestamp.

    Args:
        value: Unix timestamp (seconds since epoch) or None

    Returns:
        Parsed datetime or None if invalid/empty
    """
    if value is None:
        return None
    try:
        return datetime.utcfromtimestamp(value)
    except (ValueError, TypeError, OSError):
        return None


def parse_year_to_date(year: int | str | None, month: int = 1, day: int = 1) -> date | None:
    """
    Create a date from a year value.

    Args:
        year: Year as int or string
        month: Month (default: January)
        day: Day (default: 1st)

    Returns:
        Date or None if invalid
    """
    if year is None:
        return None
    try:
        return date(int(year), month, day)
    except (ValueError, TypeError):
        return None


# ============================================================================
# Environment Configuration
# ============================================================================

def get_env_int(key: str, default: int) -> int:
    """
    Get an integer from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Integer value
    """
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_env_str(key: str, default: str = "") -> str:
    """
    Get a string from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        String value
    """
    return os.environ.get(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """
    Get a boolean from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        Boolean value (true/1/yes = True, others = False)
    """
    value = os.environ.get(key, "").lower()
    if not value:
        return default
    return value in ("true", "1", "yes", "on")


def get_env_list(key: str, default: list[str] | None = None, separator: str = ",") -> list[str]:
    """
    Get a list from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set
        separator: List separator (default: comma)

    Returns:
        List of strings
    """
    value = os.environ.get(key, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(separator) if item.strip()]


# ============================================================================
# Base Entity Mixin
# ============================================================================

class TimestampMixin(BaseModel):
    """Mixin providing created_at and updated_at timestamps."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SourceMixin(BaseModel):
    """Mixin providing source tracking fields."""

    source_url: str | None = Field(default=None, description="Source URL")


class BaseEntity(TimestampMixin, SourceMixin):
    """
    Base class for domain entities.

    Provides:
    - created_at/updated_at timestamps
    - source_url tracking
    """

    class Config:
        """Pydantic config."""

        extra = "ignore"  # Ignore extra fields from API responses
