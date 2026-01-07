"""Shared data models."""

from .document import LLMDocument
from .entity import ExtractedEntity

__all__ = [
    "LLMDocument",
    "ExtractedEntity",
]
