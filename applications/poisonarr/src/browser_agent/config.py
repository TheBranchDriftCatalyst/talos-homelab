"""Configuration for Browser Agent."""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    base_url: str = "http://localhost:11434"  # Ollama default
    temperature: float = 0.1
    max_tokens: int = 1000


@dataclass
class ActiveHours:
    """Active browsing hours configuration."""
    start: str = "06:00"
    end: str = "23:00"


@dataclass
class BrowserConfig:
    """Browser persistence configuration."""
    user_data_dir: str = ""
    persist_sessions: bool = False
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080


@dataclass
class VisionConfig:
    """Vision model configuration (for screenshot-based analysis)."""
    enabled: bool = False  # Disabled by default
    fallback_only: bool = True  # Only use when accessibility fails
    provider: str = "ollama"  # ollama | openai | anthropic
    model: str = "llava:13b"  # Local model default
    base_url: str = ""  # API base URL (empty = use default)
    api_key: str = ""  # API key (from env if empty)
    som_enabled: bool = True  # Set-of-Mark annotation


@dataclass
class GraphConfig:
    """LangGraph orchestration configuration."""
    enabled: bool = True  # Enable graph-based execution
    checkpointing: bool = True  # Enable session checkpointing


@dataclass
class ReflexionConfig:
    """Reflexion (self-critique) configuration."""
    enabled: bool = True  # Enable reflexion on failures
    max_per_session: int = 5  # Maximum reflexion cycles per session
    use_reasoner_model: bool = True  # Use larger model for reflexion
    consecutive_failures_threshold: int = 2  # Failures before reflexion


@dataclass
class PlanningConfig:
    """Plan-and-Execute configuration."""
    enabled: bool = True  # Enable upfront planning for known patterns
    pattern_library_path: str = "/data/patterns.json"  # Persist patterns here
    min_confidence: float = 0.8  # Minimum confidence to use a pattern
    learn_from_success: bool = True  # Learn new patterns from successful sessions


@dataclass
class LangSmithConfig:
    """LangSmith tracing configuration."""
    enabled: bool = False
    api_key: str = ""  # From env LANGCHAIN_API_KEY if empty
    project: str = "poisonarr"  # Project name in LangSmith
    endpoint: str = "https://api.smith.langchain.com"  # LangSmith API endpoint


@dataclass
class BrowserAgentConfig:
    """Main configuration class for Browser Agent."""

    # LLM Configuration
    litellm_url: str = "http://litellm.catalyst-llm.svc.cluster.local:4000/v1"

    # Two-model architecture
    navigator_model: str = "ollama/qwen2.5:14b"  # Medium model for navigation
    reasoner_model: str = "ollama/qwen2.5:32b"  # Large/smart for reasoning

    # Legacy single model (for backwards compatibility)
    model: str = "ollama/qwen2.5:14b"

    # Timing
    min_delay_seconds: int = 60
    max_delay_seconds: int = 300
    active_hours: ActiveHours = field(default_factory=ActiveHours)
    timezone: str = "America/Los_Angeles"

    # Mode-specific settings
    activities: Dict[str, int] = field(default_factory=dict)
    sites: Dict[str, List[str]] = field(default_factory=dict)

    # Browser settings
    browser: BrowserConfig = field(default_factory=BrowserConfig)

    # Vision settings (screenshot-based analysis)
    vision: VisionConfig = field(default_factory=VisionConfig)

    # LangSmith tracing
    langsmith: LangSmithConfig = field(default_factory=LangSmithConfig)

    # LangGraph orchestration
    graph: GraphConfig = field(default_factory=GraphConfig)

    # Reflexion (self-critique)
    reflexion: ReflexionConfig = field(default_factory=ReflexionConfig)

    # Plan-and-Execute
    planning: PlanningConfig = field(default_factory=PlanningConfig)

    # Agent mode
    mode: str = "poisonarr"  # poisonarr, researcher, monitor, etc.

    @classmethod
    def from_yaml(cls, path: str) -> "BrowserAgentConfig":
        """Load configuration from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        active_hours_data = data.get("active_hours", {})
        active_hours = ActiveHours(
            start=active_hours_data.get("start", "06:00"),
            end=active_hours_data.get("end", "23:00"),
        )

        browser_data = data.get("browser", {})
        browser = BrowserConfig(
            user_data_dir=browser_data.get("user_data_dir", ""),
            persist_sessions=browser_data.get("persist_sessions", False),
            headless=browser_data.get("headless", True),
            viewport_width=browser_data.get("viewport_width", 1920),
            viewport_height=browser_data.get("viewport_height", 1080),
        )

        vision_data = data.get("vision", {})
        vision = VisionConfig(
            enabled=vision_data.get("enabled", False),
            fallback_only=vision_data.get("fallback_only", True),
            provider=vision_data.get("provider", "ollama"),
            model=vision_data.get("model", "llava:13b"),
            base_url=vision_data.get("base_url", ""),
            api_key=vision_data.get("api_key", os.environ.get("OPENAI_API_KEY", "")),
            som_enabled=vision_data.get("som_enabled", True),
        )

        graph_data = data.get("graph", {})
        graph = GraphConfig(
            enabled=graph_data.get("enabled", True),
            checkpointing=graph_data.get("checkpointing", True),
        )

        reflexion_data = data.get("reflexion", {})
        reflexion = ReflexionConfig(
            enabled=reflexion_data.get("enabled", True),
            max_per_session=reflexion_data.get("max_per_session", 5),
            use_reasoner_model=reflexion_data.get("use_reasoner_model", True),
            consecutive_failures_threshold=reflexion_data.get("consecutive_failures_threshold", 2),
        )

        planning_data = data.get("planning", {})
        planning = PlanningConfig(
            enabled=planning_data.get("enabled", True),
            pattern_library_path=planning_data.get("pattern_library_path", "/data/patterns.json"),
            min_confidence=planning_data.get("min_confidence", 0.8),
            learn_from_success=planning_data.get("learn_from_success", True),
        )

        langsmith_data = data.get("langsmith", {})
        langsmith = LangSmithConfig(
            enabled=langsmith_data.get("enabled", os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"),
            api_key=langsmith_data.get("api_key", os.environ.get("LANGCHAIN_API_KEY", "")),
            project=langsmith_data.get("project", os.environ.get("LANGCHAIN_PROJECT", "poisonarr")),
            endpoint=langsmith_data.get("endpoint", os.environ.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")),
        )

        # Support both old single-model and new two-model config
        default_model = data.get("model", "ollama/qwen2.5:7b")

        return cls(
            litellm_url=data.get(
                "litellm_url",
                "http://litellm.catalyst-llm.svc.cluster.local:4000/v1",
            ),
            navigator_model=data.get("navigator_model", default_model),
            reasoner_model=data.get("reasoner_model", data.get("model", "ollama/qwen2.5:32b")),
            model=default_model,
            min_delay_seconds=data.get("min_delay_seconds", 60),
            max_delay_seconds=data.get("max_delay_seconds", 300),
            active_hours=active_hours,
            timezone=data.get("timezone", "America/Los_Angeles"),
            activities=data.get("activities", {}),
            sites=data.get("sites", {}),
            browser=browser,
            vision=vision,
            langsmith=langsmith,
            graph=graph,
            reflexion=reflexion,
            planning=planning,
            mode=data.get("mode", "poisonarr"),
        )

    @classmethod
    def load(cls) -> "BrowserAgentConfig":
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
