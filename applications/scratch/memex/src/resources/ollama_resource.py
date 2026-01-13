"""Ollama Dagster Resource."""

import os

import httpx
from dagster import ConfigurableResource


class OllamaResource(ConfigurableResource):
    """
    Dagster resource for Ollama LLM.

    Provides embedding generation and text completion.
    """

    url: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate text completion."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client() as client:
            response = client.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")

    def get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        with httpx.Client() as client:
            response = client.post(
                f"{self.url}/api/embeddings",
                json={
                    "model": self.embedding_model,
                    "prompt": text,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json().get("embedding", [])

    def list_models(self) -> list[dict]:
        """List available models."""
        with httpx.Client() as client:
            response = client.get(f"{self.url}/api/tags", timeout=10.0)
            response.raise_for_status()
            return response.json().get("models", [])
