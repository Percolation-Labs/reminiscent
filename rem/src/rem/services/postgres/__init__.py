"""
PostgreSQL service for CloudNativePG database operations.
"""

from .diff_service import DiffService, SchemaDiff
from .programmable_diff_service import (
    DiffResult,
    ObjectDiff,
    ObjectType,
    ProgrammableDiffService,
)
from .repository import Repository
from .service import PostgresService


_postgres_instance: PostgresService | None = None


def get_postgres_service() -> PostgresService | None:
    """
    Get PostgresService singleton instance.

    Returns None if Postgres is disabled.
    Uses singleton pattern to prevent connection pool exhaustion.
    """
    global _postgres_instance

    from ...settings import settings

    if not settings.postgres.enabled:
        return None

    if _postgres_instance is None:
        _postgres_instance = PostgresService()

    return _postgres_instance


__all__ = [
    "DiffResult",
    "DiffService",
    "ObjectDiff",
    "ObjectType",
    "PostgresService",
    "ProgrammableDiffService",
    "Repository",
    "SchemaDiff",
    "get_postgres_service",
]
