"""Embeddings service for background embedding generation."""

from .api import generate_embedding, generate_embedding_async
from .worker import EmbeddingTask, EmbeddingWorker

__all__ = [
    "EmbeddingTask",
    "EmbeddingWorker",
    "generate_embedding",
    "generate_embedding_async",
]
