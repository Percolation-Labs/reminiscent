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


def get_postgres_service() -> PostgresService | None:
    """
    Get PostgresService instance.

    Returns None if Postgres is disabled.
    """
    from ...settings import settings

    if not settings.postgres.enabled:
        return None

    return PostgresService()


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
