"""
Shared utilities for corpus-core.

Provides common patterns used across domains:
- Date/datetime parsing
- Environment variable handling with centralized registry
- Base entity mixins
"""

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, TypeVar

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
# Environment Variable Registry
# ============================================================================

class EnvVarType(str, Enum):
    """Type of environment variable."""

    STRING = "string"
    INT = "int"
    BOOL = "bool"
    LIST = "list"


@dataclass
class EnvVarInfo:
    """Information about a registered environment variable."""

    name: str
    var_type: EnvVarType
    default: Any
    description: str = ""
    domain: str = ""  # e.g., "congress", "edgar", "reddit", "dagster"
    required: bool = False
    secret: bool = False  # If True, mask value in dumps

    def get_current_value(self) -> Any:
        """Get current value from environment."""
        raw = os.environ.get(self.name)
        if raw is None:
            return self.default

        if self.var_type == EnvVarType.INT:
            try:
                return int(raw)
            except ValueError:
                return self.default
        elif self.var_type == EnvVarType.BOOL:
            return raw.lower() in ("true", "1", "yes", "on")
        elif self.var_type == EnvVarType.LIST:
            return [item.strip() for item in raw.split(",") if item.strip()]
        else:
            return raw

    def is_set(self) -> bool:
        """Check if variable is explicitly set in environment."""
        return self.name in os.environ

    def to_dict(self, include_value: bool = True) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "name": self.name,
            "type": self.var_type.value,
            "default": self.default,
            "description": self.description,
            "domain": self.domain,
            "required": self.required,
            "is_set": self.is_set(),
        }
        if include_value:
            value = self.get_current_value()
            if self.secret and self.is_set():
                result["value"] = "***REDACTED***"
            else:
                result["value"] = value
        return result


class EnvRegistry:
    """
    Centralized registry for environment variables.

    Automatically tracks all env vars accessed via get_env_* functions.
    Provides inspection and documentation capabilities.
    """

    _instance: "EnvRegistry | None" = None
    _vars: dict[str, EnvVarInfo]

    def __new__(cls) -> "EnvRegistry":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._vars = {}
        return cls._instance

    def register(
        self,
        name: str,
        var_type: EnvVarType,
        default: Any,
        description: str = "",
        domain: str = "",
        required: bool = False,
        secret: bool = False,
    ) -> EnvVarInfo:
        """
        Register an environment variable.

        Args:
            name: Variable name (e.g., "MAX_BILLS")
            var_type: Type of variable
            default: Default value
            description: Human-readable description
            domain: Domain/group (e.g., "congress", "edgar")
            required: Whether variable is required
            secret: Whether to mask value in dumps

        Returns:
            EnvVarInfo for the registered variable
        """
        # Update existing registration with more info if provided
        if name in self._vars:
            existing = self._vars[name]
            if description and not existing.description:
                existing.description = description
            if domain and not existing.domain:
                existing.domain = domain
            if required:
                existing.required = required
            if secret:
                existing.secret = secret
            return existing

        info = EnvVarInfo(
            name=name,
            var_type=var_type,
            default=default,
            description=description,
            domain=domain,
            required=required,
            secret=secret,
        )
        self._vars[name] = info
        return info

    def get(self, name: str) -> EnvVarInfo | None:
        """Get info for a registered variable."""
        return self._vars.get(name)

    def all(self) -> dict[str, EnvVarInfo]:
        """Get all registered variables."""
        return dict(self._vars)

    def by_domain(self, domain: str) -> dict[str, EnvVarInfo]:
        """Get variables for a specific domain."""
        return {k: v for k, v in self._vars.items() if v.domain == domain}

    def domains(self) -> list[str]:
        """Get list of all domains."""
        return sorted(set(v.domain for v in self._vars.values() if v.domain))

    def to_dict(self, include_values: bool = True) -> dict[str, Any]:
        """
        Export registry as dictionary.

        Args:
            include_values: Include current values (respects secret flag)

        Returns:
            Dictionary with all registered variables
        """
        return {
            name: info.to_dict(include_value=include_values)
            for name, info in sorted(self._vars.items())
        }

    def to_json(self, include_values: bool = True, indent: int = 2) -> str:
        """Export registry as JSON string."""
        return json.dumps(self.to_dict(include_values), indent=indent)

    def to_markdown(self, include_values: bool = False) -> str:
        """
        Export registry as markdown documentation.

        Args:
            include_values: Include current values column

        Returns:
            Markdown table string
        """
        lines = ["# Environment Variables\n"]

        # Group by domain
        domains = self.domains() or [""]
        for domain in domains:
            domain_vars = self.by_domain(domain) if domain else {
                k: v for k, v in self._vars.items() if not v.domain
            }
            if not domain_vars:
                continue

            if domain:
                lines.append(f"\n## {domain.title()}\n")
            else:
                lines.append("\n## General\n")

            # Table header
            if include_values:
                lines.append("| Variable | Type | Default | Current | Description |")
                lines.append("|----------|------|---------|---------|-------------|")
            else:
                lines.append("| Variable | Type | Default | Description |")
                lines.append("|----------|------|---------|-------------|")

            # Table rows
            for name, info in sorted(domain_vars.items()):
                default_str = f"`{info.default}`" if info.default != "" else '""'
                if include_values:
                    if info.secret and info.is_set():
                        value_str = "***"
                    else:
                        value_str = f"`{info.get_current_value()}`"
                    lines.append(
                        f"| `{name}` | {info.var_type.value} | {default_str} | {value_str} | {info.description} |"
                    )
                else:
                    lines.append(
                        f"| `{name}` | {info.var_type.value} | {default_str} | {info.description} |"
                    )

        return "\n".join(lines)

    def to_env_example(self) -> str:
        """
        Export registry as .env.example file content.

        Returns:
            .env file format string
        """
        lines = ["# Environment Variables for corpus-pipelines", "#"]

        domains = self.domains() or [""]
        for domain in domains:
            domain_vars = self.by_domain(domain) if domain else {
                k: v for k, v in self._vars.items() if not v.domain
            }
            if not domain_vars:
                continue

            if domain:
                lines.append(f"\n# === {domain.upper()} ===")

            for name, info in sorted(domain_vars.items()):
                if info.description:
                    lines.append(f"# {info.description}")
                if info.secret:
                    lines.append(f"# {name}=your-secret-here")
                else:
                    lines.append(f"{name}={info.default}")

        return "\n".join(lines)

    def validate(self) -> list[str]:
        """
        Validate required variables are set.

        Returns:
            List of error messages for missing required variables
        """
        errors = []
        for name, info in self._vars.items():
            if info.required and not info.is_set():
                errors.append(f"Required environment variable {name} is not set")
        return errors

    def clear(self) -> None:
        """Clear all registered variables (mainly for testing)."""
        self._vars.clear()


# Global registry instance
_registry = EnvRegistry()


def get_env_registry() -> EnvRegistry:
    """Get the global environment variable registry."""
    return _registry


# ============================================================================
# Environment Configuration Functions
# ============================================================================

def get_env_int(
    key: str,
    default: int,
    description: str = "",
    domain: str = "",
    required: bool = False,
) -> int:
    """
    Get an integer from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set or invalid
        description: Human-readable description (for registry)
        domain: Domain/group for organization (e.g., "congress")
        required: Whether variable is required

    Returns:
        Integer value
    """
    _registry.register(
        name=key,
        var_type=EnvVarType.INT,
        default=default,
        description=description,
        domain=domain,
        required=required,
    )
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_env_str(
    key: str,
    default: str = "",
    description: str = "",
    domain: str = "",
    required: bool = False,
    secret: bool = False,
) -> str:
    """
    Get a string from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set
        description: Human-readable description (for registry)
        domain: Domain/group for organization
        required: Whether variable is required
        secret: Whether to mask in dumps (e.g., API keys)

    Returns:
        String value
    """
    _registry.register(
        name=key,
        var_type=EnvVarType.STRING,
        default=default,
        description=description,
        domain=domain,
        required=required,
        secret=secret,
    )
    return os.environ.get(key, default)


def get_env_bool(
    key: str,
    default: bool = False,
    description: str = "",
    domain: str = "",
) -> bool:
    """
    Get a boolean from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set
        description: Human-readable description (for registry)
        domain: Domain/group for organization

    Returns:
        Boolean value (true/1/yes = True, others = False)
    """
    _registry.register(
        name=key,
        var_type=EnvVarType.BOOL,
        default=default,
        description=description,
        domain=domain,
    )
    value = os.environ.get(key, "").lower()
    if not value:
        return default
    return value in ("true", "1", "yes", "on")


def get_env_list(
    key: str,
    default: list[str] | None = None,
    separator: str = ",",
    description: str = "",
    domain: str = "",
) -> list[str]:
    """
    Get a list from environment variable.

    Args:
        key: Environment variable name
        default: Default value if not set
        separator: List separator (default: comma)
        description: Human-readable description (for registry)
        domain: Domain/group for organization

    Returns:
        List of strings
    """
    _registry.register(
        name=key,
        var_type=EnvVarType.LIST,
        default=default or [],
        description=description,
        domain=domain,
    )
    value = os.environ.get(key, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(separator) if item.strip()]


# ============================================================================
# Convenience Functions
# ============================================================================

def dump_env_config(format: str = "json", include_values: bool = True) -> str:
    """
    Dump all registered environment variables.

    Args:
        format: Output format ("json", "markdown", "env")
        include_values: Include current values

    Returns:
        Formatted string
    """
    if format == "markdown":
        return _registry.to_markdown(include_values=include_values)
    elif format == "env":
        return _registry.to_env_example()
    else:
        return _registry.to_json(include_values=include_values)


def validate_env_config() -> list[str]:
    """
    Validate all required environment variables are set.

    Returns:
        List of error messages (empty if all valid)
    """
    return _registry.validate()


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
