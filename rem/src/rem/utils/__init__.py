"""
REM Utilities

Utility functions and helpers for the REM system:
- sql_types: Pydantic to PostgreSQL type mapping
- embeddings: Vector embeddings generation using requests library
- user_id: Deterministic UUID generation from email addresses
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
from .user_id import (
    email_to_user_id,
    is_valid_uuid,
    user_id_to_uuid,
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
    # User ID
    "email_to_user_id",
    "user_id_to_uuid",
    "is_valid_uuid",
]
