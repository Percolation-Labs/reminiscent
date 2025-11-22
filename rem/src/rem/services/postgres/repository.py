"""Generic repository for entity persistence.

Single repository class that works with any Pydantic model type.
No need for model-specific repository classes.

Usage:
    from rem.models.entities import Message
    from rem.services.repositories import Repository

    repo = Repository(db, Message, table_name="messages")
    message = await repo.upsert(message_instance)
    messages = await repo.find({"session_id": "abc", "tenant_id": "xyz"})
"""

import json
from typing import Any, Generic, Type, TypeVar

from loguru import logger
from pydantic import BaseModel

from .service import PostgresService
from .sql_builder import (
    build_count,
    build_delete,
    build_insert,
    build_select,
    build_upsert,
)
from ...settings import settings


def get_postgres_service() -> PostgresService | None:
    """
    Get PostgresService instance with connection string from settings.

    Returns None if Postgres is disabled.
    """
    if not settings.postgres.enabled:
        return None

    return PostgresService()

T = TypeVar("T", bound=BaseModel)

# Known JSONB fields from CoreModel that need deserialization
JSONB_FIELDS = {"graph_edges", "metadata"}


class Repository(Generic[T]):
    """Generic repository for any Pydantic model type."""

    def __init__(
        self,
        model_class: Type[T],
        table_name: str | None = None,
        db: PostgresService | None = None,
    ):
        """
        Initialize repository.

        Args:
            model_class: Pydantic model class (e.g., Message, Resource)
            table_name: Optional table name (defaults to lowercase model name + 's')
            db: Optional PostgresService instance (creates from settings if None)
        """
        self.db = db or get_postgres_service()
        self.model_class = model_class
        self.table_name = table_name or f"{model_class.__name__.lower()}s"

    async def upsert(self, records: T | list[T]) -> T | list[T]:
        """
        Upsert single record or list of records (create or update on ID conflict).

        Accepts both single items and lists - no need to distinguish batch vs non-batch.
        Single items are coerced to lists internally for processing.

        Args:
            records: Single model instance or list of model instances

        Returns:
            Single record or list of records with generated IDs (matches input type)
        """
        # Coerce single item to list for uniform processing
        is_single = not isinstance(records, list)
        records_list = [records] if is_single else records

        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, skipping {self.model_class.__name__} upsert")
            return records

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        for record in records_list:
            sql, params = build_upsert(record, self.table_name, conflict_field="id", return_id=True)
            async with self.db.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                if row and "id" in row:
                    record.id = row["id"]

        # Return single item or list to match input type
        return records_list[0] if is_single else records_list

    async def get_by_id(self, record_id: str, tenant_id: str) -> T | None:
        """
        Get a single record by ID.

        Args:
            record_id: Record identifier
            tenant_id: Tenant identifier for multi-tenancy isolation

        Returns:
            Model instance or None if not found
        """
        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, returning None for {self.model_class.__name__} get")
            return None

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query, record_id, tenant_id)

        if not row:
            return None

        # PostgreSQL JSONB columns come back as strings, need to parse them
        row_dict = dict(row)
        return self.model_class.model_validate(row_dict)

    async def find(
        self,
        filters: dict[str, Any],
        order_by: str = "created_at ASC",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[T]:
        """
        Find records matching filters.

        Args:
            filters: Dict of field -> value filters (AND-ed together)
            order_by: ORDER BY clause (default: "created_at ASC")
            limit: Optional limit on number of records
            offset: Offset for pagination

        Returns:
            List of model instances

        Example:
            messages = await repo.find({
                "session_id": "abc-123",
                "tenant_id": "acme-corp",
                "user_id": "alice"
            })
        """
        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, returning empty {self.model_class.__name__} list")
            return []

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        sql, params = build_select(
            self.model_class,
            self.table_name,
            filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [self.model_class.model_validate(dict(row)) for row in rows]

    async def find_one(self, filters: dict[str, Any]) -> T | None:
        """
        Find single record matching filters.

        Args:
            filters: Dict of field -> value filters

        Returns:
            Model instance or None if not found
        """
        results = await self.find(filters, limit=1)
        return results[0] if results else None

    async def get_by_session(
        self, session_id: str, tenant_id: str, user_id: str | None = None
    ) -> list[T]:
        """
        Get all records for a session (convenience method for Message model).

        Args:
            session_id: Session identifier
            tenant_id: Tenant identifier
            user_id: Optional user identifier

        Returns:
            List of model instances ordered by created_at
        """
        filters = {"session_id": session_id, "tenant_id": tenant_id}
        if user_id:
            filters["user_id"] = user_id

        return await self.find(filters, order_by="created_at ASC")

    async def update(self, record: T) -> T:
        """
        Update a record (upsert).

        Args:
            record: Model instance to update

        Returns:
            Updated record
        """
        return await self.create(record)

    async def delete(self, record_id: str, tenant_id: str) -> bool:
        """
        Soft delete a record (sets deleted_at).

        Args:
            record_id: Record identifier
            tenant_id: Tenant identifier for multi-tenancy isolation

        Returns:
            True if deleted, False if not found
        """
        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, skipping {self.model_class.__name__} deletion")
            return False

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        sql, params = build_delete(self.table_name, record_id, tenant_id)

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)

        return row is not None

    async def count(self, filters: dict[str, Any]) -> int:
        """
        Count records matching filters.

        Args:
            filters: Dict of field -> value filters

        Returns:
            Count of matching records
        """
        if not settings.postgres.enabled or not self.db:
            return 0

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        sql, params = build_count(self.table_name, filters)

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)

        return row[0] if row else 0
