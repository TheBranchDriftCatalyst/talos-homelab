"""
Shared data models.

Provides Pydantic models for documents and entities.
"""

from corpus_core.models.document import Document
from corpus_core.models.entity import ExtractedEntity

__all__ = ["Document", "ExtractedEntity"]
