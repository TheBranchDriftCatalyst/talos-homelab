"""
Data loaders for various storage backends.

Provides loaders for:
- Parquet files (local dataset storage)
- Neo4j (knowledge graph)
- Embedding generation
"""

from corpus_core.loaders.parquet_loader import ParquetLoader
from corpus_core.loaders.neo4j_loader import Neo4jLoader
from corpus_core.loaders.embedding_service import EmbeddingService

__all__ = ["ParquetLoader", "Neo4jLoader", "EmbeddingService"]
