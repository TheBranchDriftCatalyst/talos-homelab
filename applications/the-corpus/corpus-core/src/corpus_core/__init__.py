"""
corpus-core: Shared ETL infrastructure for the-corpus NER training data pipeline.

This package provides:
- clients: Base API client patterns with rate limiting and retry logic
- extractors: NER extraction using LLM with JSON-LD schema annotations
- loaders: Data loaders for Neo4j, Parquet, and local storage
- models: Shared Pydantic models for documents and entities
- schema: Ontology system and schema generators
"""

from corpus_core.models.document import Document
from corpus_core.models.entity import ExtractedEntity

__version__ = "0.1.0"

__all__ = [
    "Document",
    "ExtractedEntity",
    "__version__",
]
