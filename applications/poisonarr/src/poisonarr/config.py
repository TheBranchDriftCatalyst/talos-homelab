"""Configuration handling for Poisonarr."""

import os
from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class ActiveHours:
    """Active browsing hours configuration."""

    start: str = "06:00"
    end: str = "23:00"


@dataclass
class Config:
    """Main configuration class."""

    litellm_url: str = "http://litellm.catalyst-llm.svc.cluster.local:4000/v1"
    model: str = "ollama/llama3.2"
    min_delay_seconds: int = 60
    max_delay_seconds: int = 300
    active_hours: ActiveHours = field(default_factory=ActiveHours)
    timezone: str = "America/Los_Angeles"
    activities: Dict[str, int] = field(default_factory=dict)
    sites: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load configuration from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        active_hours_data = data.get("active_hours", {})
        active_hours = ActiveHours(
            start=active_hours_data.get("start", "06:00"),
            end=active_hours_data.get("end", "23:00"),
        )

        return cls(
            litellm_url=data.get(
                "litellm_url",
                "http://litellm.catalyst-llm.svc.cluster.local:4000/v1",
            ),
            model=data.get("model", "ollama/llama3.2"),
            min_delay_seconds=data.get("min_delay_seconds", 60),
            max_delay_seconds=data.get("max_delay_seconds", 300),
            active_hours=active_hours,
            timezone=data.get("timezone", "America/Los_Angeles"),
            activities=data.get("activities", {}),
            sites=data.get("sites", {}),
        )

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment or default path."""
        config_path = os.environ.get("CONFIG_PATH", "/config/config.yaml")

        if os.path.exists(config_path):
            return cls.from_yaml(config_path)

        # Return default config if file doesn't exist
        return cls(
            activities={
                "news": 25,
                "shopping": 20,
                "tech": 20,
                "search": 25,
                "social": 10,
            },
            sites={
                "news": ["cnn.com", "bbc.com", "reuters.com"],
                "shopping": ["amazon.com", "ebay.com", "walmart.com"],
                "tech": ["github.com", "stackoverflow.com"],
                "search_engines": ["google.com", "duckduckgo.com"],
                "social": ["reddit.com"],
            },
        )
