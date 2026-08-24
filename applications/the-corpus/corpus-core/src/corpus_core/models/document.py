"""
Document Model

Generic document type for ETL processing and NER training.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Document(BaseModel):
    """
    Generic document for NER training data preparation.

    Represents a piece of content that can be processed for:
    - Entity extraction
    - Summarization
    - Embedding generation
    - Training data preparation
    """

    id: str = Field(description="Unique document identifier")
    title: str = Field(description="Document title")
    content: str = Field(description="Main document content/text")

    # Metadata
    source: str = Field(description="Source system (e.g., 'congress.gov', 'sec.gov', 'reddit')")
    source_url: str | None = Field(default=None, description="Original source URL")
    document_type: str = Field(description="Type of document (e.g., 'bill', '10-k', 'submission')")

    # Domain context
    domain: str = Field(description="Domain this document belongs to (e.g., 'congress', 'edgar', 'reddit')")
    entity_type: str | None = Field(default=None, description="Primary entity type if known")

    # Processing metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: datetime | None = Field(default=None)

    # Additional structured data
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Extracted content sections
    sections: dict[str, str] = Field(
        default_factory=dict,
        description="Named sections of the document (e.g., 'summary', 'item_1', 'item_1a')"
    )

    def get_text_for_extraction(self) -> str:
        """Get concatenated text for entity extraction."""
        parts = [self.title, self.content]
        parts.extend(self.sections.values())
        return "\n\n".join(part for part in parts if part)

    def get_text_for_embedding(self) -> str:
        """Get text representation for embedding (truncated for efficiency)."""
        return f"{self.title}\n{self.content[:2000]}"

    def to_training_example(self) -> dict[str, Any]:
        """Convert to a training data example format."""
        return {
            "id": self.id,
            "text": self.get_text_for_extraction(),
            "domain": self.domain,
            "source": self.source,
            "metadata": self.metadata,
        }

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat(),
        }
    }
