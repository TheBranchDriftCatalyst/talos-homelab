"""
Embedding Service

Generate vector embeddings via Ollama for semantic search.
"""

import httpx
import structlog

logger = structlog.get_logger()


class EmbeddingService:
    """
    Generate text embeddings using Ollama.
    # TODO: update this to a 1024 dimension model, and one that can work 
    # on a powerful mac pro (check this computer specs, it can run a 7-12b model)
    Uses nomic-embed-text by default (384 dimensions).
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ):
        self.ollama_url = ollama_url
        self.model = model
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions (cached after first call)."""
        if self._dimensions is None:
            # Get dimensions from a test embedding
            test_embedding = self.get_embedding("test")
            self._dimensions = len(test_embedding)
        return self._dimensions

    def get_embedding(self, text: str) -> list[float]:
        """
        Get embedding vector for text.

        Returns list of floats representing the embedding.
        """
        with httpx.Client() as client:
            response = client.post(
                f"{self.ollama_url}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

        embedding = result.get("embedding", [])
        logger.debug("embedding_generated", text_length=len(text), dimensions=len(embedding))
        return embedding

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Get embeddings for multiple texts.

        Note: Ollama doesn't support batch embeddings natively,
        so this makes sequential calls.
        """
        embeddings = []
        for text in texts:
            embedding = self.get_embedding(text)
            embeddings.append(embedding)

        logger.info("batch_embeddings_generated", count=len(embeddings))
        return embeddings

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math

        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(x * x for x in b))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)
