"""
corpus-core: Shared ETL infrastructure for the-corpus NER training data pipeline.

This package provides:
- clients: Base API client patterns with rate limiting and retry logic
- extractors: NER extraction using LLM with JSON-LD schema annotations
- loaders: Data loaders for Neo4j, Parquet, and local storage
- models: Shared Pydantic models for documents and entities
- schema: Ontology system and schema generators
- utils: Shared utilities (date parsing, env config, base entities)
"""

from corpus_core.models.document import Document
from corpus_core.models.entity import ExtractedEntity
from corpus_core.utils import (
    BaseEntity,
    get_env_int,
    get_env_str,
    get_env_bool,
    get_env_list,
    parse_date,
    parse_datetime,
    parse_timestamp,
    parse_year_to_date,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "Document",
    "ExtractedEntity",
    # Base classes
    "BaseEntity",
    # Utilities
    "get_env_int",
    "get_env_str",
    "get_env_bool",
    "get_env_list",
    "parse_date",
    "parse_datetime",
    "parse_timestamp",
    "parse_year_to_date",
    # Version
    "__version__",
]
