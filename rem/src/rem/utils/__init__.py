"""
REM Utilities

Utility functions and helpers for the REM system:
- sql_types: Pydantic to PostgreSQL type mapping
- embeddings: Vector embeddings generation using requests library
"""

from .embeddings import (
    EmbeddingError,
    RateLimitError,
    generate_embeddings,
    get_embedding_dimension,
)
from .sql_types import (
    get_column_definition,
    get_sql_type,
    model_to_create_table,
    model_to_upsert,
)

__all__ = [
    # SQL Types
    "get_sql_type",
    "get_column_definition",
    "model_to_create_table",
    "model_to_upsert",
    # Embeddings
    "generate_embeddings",
    "get_embedding_dimension",
    "EmbeddingError",
    "RateLimitError",
]
