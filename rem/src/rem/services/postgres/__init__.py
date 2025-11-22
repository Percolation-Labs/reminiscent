"""
PostgreSQL service for CloudNativePG database operations.
"""

from .repository import Repository
from .service import PostgresService


def get_postgres_service() -> PostgresService | None:
    """
    Get PostgresService instance with connection string from settings.

    Returns None if Postgres is disabled.
    """
    from ...settings import settings

    if not settings.postgres.enabled:
        return None

    return PostgresService(
        connection_string=settings.postgres.connection_string,
        pool_size=settings.postgres.pool_size,
    )


__all__ = ["PostgresService", "get_postgres_service", "Repository"]
