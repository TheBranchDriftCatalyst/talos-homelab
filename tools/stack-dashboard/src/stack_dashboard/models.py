"""Data models for stack configuration."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class CredentialType(Enum):
    """Type of credential."""
    API_KEY = "api_key"
    USER_PASS = "userpass"
    TOKEN = "token"


class CredentialSource(Enum):
    """Source of credential extraction."""
    SECRET = "secret"  # Kubernetes secret
    CONFIG_XML = "config_xml"  # *arr style config.xml
    CONFIG_JSON = "config_json"  # JSON config file
    PREFERENCES_XML = "preferences_xml"  # Plex style


@dataclass
class CredentialConfig:
    """Configuration for extracting a credential."""
    name: str
    display_name: str
    type: CredentialType
    source: CredentialSource

    # For SECRET source
    secret_name: str | None = None
    secret_key: str | None = None

    # For file-based sources (executed in pod)
    config_path: str | None = None
    json_path: str | None = None  # jq-style path for JSON
    xml_tag: str | None = None  # XML tag name
    xml_attribute: str | None = None  # XML attribute name

    # For userpass type
    username_key: str | None = None
    password_key: str | None = None

    # Optional static username (e.g., "postgres")
    static_username: str | None = None


@dataclass
class ServiceConfig:
    """Configuration for a service in the stack."""
    name: str
    display_name: str
    description: str = ""

    # Kubernetes resources
    deployment_name: str | None = None  # Defaults to name
    namespace: str | None = None  # Defaults to stack namespace

    # URL configuration
    url_template: str = "http://{name}.{domain}"
    port: int | None = None

    # Credential configuration
    credential: CredentialConfig | None = None

    # Volume mounts to display
    show_volumes: bool = True

    # Whether service is optional (won't show error if not deployed)
    optional: bool = False

    # Icon/emoji for display
    icon: str = "●"

    def __post_init__(self):
        if self.deployment_name is None:
            self.deployment_name = self.name


@dataclass
class ServiceGroup:
    """A group of related services."""
    name: str
    display_name: str
    services: list[ServiceConfig] = field(default_factory=list)
    icon: str = "▸"


@dataclass
class StackConfig:
    """Configuration for an entire stack."""
    name: str
    display_name: str
    namespace: str
    domain: str = "talos00"

    # Service groups
    groups: list[ServiceGroup] = field(default_factory=list)

    # Global credentials (not tied to specific service)
    global_credentials: list[CredentialConfig] = field(default_factory=list)

    # ASCII art banner (optional)
    banner: str | None = None

    # Refresh interval in seconds
    refresh_interval: float = 5.0

    @property
    def all_services(self) -> list[ServiceConfig]:
        """Get all services across all groups."""
        services = []
        for group in self.groups:
            services.extend(group.services)
        return services
