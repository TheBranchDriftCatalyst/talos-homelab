"""Credential extraction from various sources."""

import json
import re
from dataclasses import dataclass

from .k8s import K8sClient
from .models import CredentialConfig, CredentialSource, CredentialType


@dataclass
class ExtractedCredential:
    """An extracted credential."""
    config: CredentialConfig
    value: str | None
    username: str | None = None
    password: str | None = None

    @property
    def display_value(self) -> str:
        """Get displayable credential value."""
        if self.config.type == CredentialType.USER_PASS:
            if self.username and self.password:
                return f"{self.username}:{self.password}"
            return "<not found>"
        elif self.value:
            return f"apikey:{self.value}"
        return "<not found>"

    @property
    def copyable_value(self) -> str:
        """Get value suitable for copying to clipboard."""
        if self.config.type == CredentialType.USER_PASS:
            return self.password or ""
        return self.value or ""

    @property
    def is_valid(self) -> bool:
        """Check if credential was successfully extracted."""
        if self.config.type == CredentialType.USER_PASS:
            return bool(self.username and self.password)
        return bool(self.value) and self.value not in ("pending-sync", "todo", "<not found>")


class CredentialExtractor:
    """Extract credentials from various sources."""

    def __init__(self, k8s_client: K8sClient):
        self.k8s = k8s_client

    def extract(self, config: CredentialConfig, deployment_name: str | None = None) -> ExtractedCredential:
        """Extract a credential based on its configuration."""
        if config.source == CredentialSource.SECRET:
            return self._extract_from_secret(config)
        elif config.source == CredentialSource.CONFIG_XML:
            return self._extract_from_config_xml(config, deployment_name or config.name)
        elif config.source == CredentialSource.CONFIG_JSON:
            return self._extract_from_config_json(config, deployment_name or config.name)
        elif config.source == CredentialSource.PREFERENCES_XML:
            return self._extract_from_preferences_xml(config, deployment_name or config.name)
        else:
            return ExtractedCredential(config=config, value=None)

    def _extract_from_secret(self, config: CredentialConfig) -> ExtractedCredential:
        """Extract credential from Kubernetes secret."""
        if config.type == CredentialType.USER_PASS:
            username = config.static_username
            password = None

            if config.username_key and not username:
                username = self.k8s.get_secret_value(config.secret_name, config.username_key)

            if config.password_key:
                password = self.k8s.get_secret_value(config.secret_name, config.password_key)

            return ExtractedCredential(
                config=config,
                value=None,
                username=username,
                password=password,
            )
        else:
            value = self.k8s.get_secret_value(config.secret_name, config.secret_key)
            return ExtractedCredential(config=config, value=value)

    def _extract_from_config_xml(self, config: CredentialConfig, deployment_name: str) -> ExtractedCredential:
        """Extract credential from *arr style config.xml."""
        content = self.k8s.exec_in_pod(deployment_name, ["cat", config.config_path or "/config/config.xml"])
        if not content:
            return ExtractedCredential(config=config, value=None)

        # Extract value from XML tag
        tag = config.xml_tag or "ApiKey"
        pattern = rf"<{tag}>([^<]+)</{tag}>"
        match = re.search(pattern, content)

        if match:
            return ExtractedCredential(config=config, value=match.group(1))
        return ExtractedCredential(config=config, value=None)

    def _extract_from_config_json(self, config: CredentialConfig, deployment_name: str) -> ExtractedCredential:
        """Extract credential from JSON config file."""
        content = self.k8s.exec_in_pod(deployment_name, ["cat", config.config_path])
        if not content:
            return ExtractedCredential(config=config, value=None)

        try:
            data = json.loads(content)
            # Navigate JSON path (simple dot notation)
            value = data
            for key in (config.json_path or "").split("."):
                if key and isinstance(value, dict):
                    value = value.get(key)

            if isinstance(value, str):
                return ExtractedCredential(config=config, value=value)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return ExtractedCredential(config=config, value=None)

    def _extract_from_preferences_xml(self, config: CredentialConfig, deployment_name: str) -> ExtractedCredential:
        """Extract credential from Plex-style Preferences.xml."""
        content = self.k8s.exec_in_pod(
            deployment_name,
            ["cat", config.config_path or "/config/Library/Application Support/Plex Media Server/Preferences.xml"],
        )
        if not content:
            return ExtractedCredential(config=config, value=None)

        # Extract attribute value
        attr = config.xml_attribute or "PlexOnlineToken"
        pattern = rf'{attr}="([^"]+)"'
        match = re.search(pattern, content)

        if match:
            return ExtractedCredential(config=config, value=match.group(1))
        return ExtractedCredential(config=config, value=None)

    def extract_all_for_service(self, config: CredentialConfig, deployment_name: str | None = None) -> ExtractedCredential:
        """Extract credentials for a service, trying multiple sources."""
        # Try the configured source first
        result = self.extract(config, deployment_name)
        if result.is_valid:
            return result

        # If not found and source was SECRET, try extracting from pod config
        if config.source == CredentialSource.SECRET:
            # Try config.xml for *arr apps
            xml_config = CredentialConfig(
                name=config.name,
                display_name=config.display_name,
                type=config.type,
                source=CredentialSource.CONFIG_XML,
                config_path="/config/config.xml",
                xml_tag="ApiKey",
            )
            result = self._extract_from_config_xml(xml_config, deployment_name or config.name)
            if result.is_valid:
                return result

        return ExtractedCredential(config=config, value=None)
