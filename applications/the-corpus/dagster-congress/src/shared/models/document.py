"""
LLM Document Model

Generic document type for LLM processing.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LLMDocument(BaseModel):
    """
    Generic document for LLM processing.

    Represents a piece of content that can be processed by an LLM
    for entity extraction, summarization, or other tasks.
    """

    id: str = Field(description="Unique document identifier")
    title: str = Field(description="Document title")
    content: str = Field(description="Main document content/text")

    # Metadata
    source: str = Field(description="Source system (e.g., 'congress.gov')")
    source_url: str | None = Field(default=None, description="Original source URL")
    document_type: str = Field(description="Type of document (e.g., 'bill', 'member_bio')")

    # Domain context
    domain: str = Field(default="congressional", description="Domain this document belongs to")
    entity_type: str | None = Field(default=None, description="Primary entity type if known")

    # Processing metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = Field(default=None)

    # Additional structured data
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Extracted content sections
    sections: dict[str, str] = Field(
        default_factory=dict,
        description="Named sections of the document (e.g., 'summary', 'actions')"
    )

    def get_text_for_extraction(self) -> str:
        """Get concatenated text for entity extraction."""
        parts = [self.title, self.content]
        parts.extend(self.sections.values())
        return "\n\n".join(part for part in parts if part)

    def get_text_for_embedding(self) -> str:
        """Get text representation for embedding."""
        return f"{self.title}\n{self.content[:2000]}"

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
