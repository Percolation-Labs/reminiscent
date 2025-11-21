"""
PostgreSQL service for CloudNativePG database operations.
"""

from .service import PostgresService


def get_postgres_service() -> PostgresService | None:
    """
    Get PostgresService instance with connection string from settings.

    Returns None if Postgres is disabled.
    """
    from ...settings import settings

    if not settings.postgres.enabled:
        return None

    connection_string = (
        f"postgresql://{settings.postgres.user}:{settings.postgres.password}@"
        f"{settings.postgres.host}:{settings.postgres.port}/{settings.postgres.database}"
    )

    return PostgresService(
        connection_string=connection_string, pool_size=settings.postgres.pool_size or 10
    )


__all__ = ["PostgresService", "get_postgres_service"]
