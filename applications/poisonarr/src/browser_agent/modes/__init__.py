"""Agent modes - different behaviors for the browser agent."""

from .base import AgentMode
from .poisonarr import PoisonarrMode
from .researcher import ResearcherMode
from .monitor import MonitorMode

__all__ = ["AgentMode", "PoisonarrMode", "ResearcherMode", "MonitorMode"]
