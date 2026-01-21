"""gRPC MCP Interface for Knowledge Graph."""

from .server import serve
from .handlers import KnowledgeGraphServicer

__all__ = ["serve", "KnowledgeGraphServicer"]
