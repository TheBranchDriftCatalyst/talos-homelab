"""Browser Agent - Generic browser automation framework.

This package provides a flexible browser automation system with:
- Navigator: Small/fast model for browser actions (click, type, scroll, goto)
- Reasoner: Large/smart model for content understanding and extraction
- Modes: Different agent behaviors (Poisonarr, Researcher, etc.)

Architecture:
    ┌─────────────────────────────────────────┐
    │              Agent Mode                  │
    │  (Poisonarr, Researcher, Monitor, etc.) │
    └─────────────────┬───────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
    ┌───────────┐          ┌───────────┐
    │ Navigator │          │ Reasoner  │
    │ (7B fast) │          │(32B smart)│
    └─────┬─────┘          └───────────┘
          │
          ▼
    ┌───────────┐
    │ Browser   │
    │Controller │
    └───────────┘
"""

__version__ = "0.2.0"

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == "Navigator":
        from .core.navigator import Navigator
        return Navigator
    elif name == "BrowserController":
        from .core.browser import BrowserController
        return BrowserController
    elif name == "BrowserTools":
        from .core.browser import BrowserTools
        return BrowserTools
    elif name == "Reasoner":
        from .reasoning.reasoner import Reasoner
        return Reasoner
    elif name == "AgentMode":
        from .modes.base import AgentMode
        return AgentMode
    elif name == "PoisonarrMode":
        from .modes.poisonarr import PoisonarrMode
        return PoisonarrMode
    elif name == "BrowserAgentConfig":
        from .config import BrowserAgentConfig
        return BrowserAgentConfig
    elif name == "MemoryManager":
        from .memory import MemoryManager
        return MemoryManager
    elif name == "get_server":
        from .server import get_server
        return get_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Navigator",
    "BrowserController",
    "BrowserTools",
    "Reasoner",
    "AgentMode",
    "PoisonarrMode",
    "BrowserAgentConfig",
    "MemoryManager",
    "get_server",
]
