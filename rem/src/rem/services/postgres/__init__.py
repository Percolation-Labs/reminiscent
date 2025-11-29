"""
PostgreSQL service for CloudNativePG database operations.
"""

from .diff_service import DiffService, SchemaDiff
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


__all__ = ["PostgresService", "get_postgres_service", "Repository", "DiffService", "SchemaDiff"]
