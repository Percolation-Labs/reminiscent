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
from typing import Any, Generic, Type, TypeVar, TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel

from .sql_builder import (
    build_count,
    build_delete,
    build_insert,
    build_select,
    build_upsert,
)
from ...settings import settings

if TYPE_CHECKING:
    from .service import PostgresService


def get_postgres_service() -> "PostgresService | None":
    """
    Get PostgresService singleton from parent module.

    Uses late import to avoid circular import issues.
    Previously had a separate _postgres_instance here which caused
    "pool not connected" errors due to duplicate connection pools.
    """
    # Late import to avoid circular import (repository.py imported by __init__.py)
    from rem.services.postgres import get_postgres_service as _get_singleton
    return _get_singleton()

T = TypeVar("T", bound=BaseModel)

# Known JSONB fields from CoreModel that need deserialization
JSONB_FIELDS = {"graph_edges", "metadata"}


class Repository(Generic[T]):
    """Generic repository for any Pydantic model type."""

    def __init__(
        self,
        model_class: Type[T],
        table_name: str | None = None,
        db: "PostgresService | None" = None,
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

    async def upsert(
        self,
        records: T | list[T],
        embeddable_fields: list[str] | None = None,
        generate_embeddings: bool = True,
    ) -> T | list[T]:
        """
        Upsert single record or list of records (create or update on ID conflict).

        Accepts both single items and lists - no need to distinguish batch vs non-batch.
        Single items are coerced to lists internally for processing.

        Args:
            records: Single model instance or list of model instances
            embeddable_fields: Optional list of fields to generate embeddings for.
                              If None, auto-detects 'content' field if present.
            generate_embeddings: Whether to queue embedding generation tasks (default: True)

        Returns:
            Single record or list of records with generated IDs (matches input type)
        """
        # Coerce single item to list for uniform processing
        is_single = not isinstance(records, list)
        records_list: list[T]
        if is_single:
            records_list = [records]  # type: ignore[list-item]
        else:
            records_list = records  # Type narrowed by isinstance check

        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, skipping {self.model_class.__name__} upsert")
            return records

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

        for record in records_list:
            sql, params = build_upsert(record, self.table_name, conflict_field="id", return_id=True)
            async with self.db.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                if row and "id" in row:
                    record.id = row["id"]  # type: ignore[attr-defined]

        # Queue embedding generation if requested and worker is available
        if generate_embeddings and self.db.embedding_worker:
            from rem.services.embeddings import EmbeddingTask
            from .register_type import should_embed_field

            # Auto-detect embeddable fields if not specified
            if embeddable_fields is None:
                embeddable_fields = [
                    field_name
                    for field_name, field_info in self.model_class.model_fields.items()
                    if should_embed_field(field_name, field_info)
                ]

            if embeddable_fields:
                for record in records_list:
                    for field_name in embeddable_fields:
                        content = getattr(record, field_name, None)
                        if content and isinstance(content, str):
                            task = EmbeddingTask(
                                task_id=f"{record.id}-{field_name}",  # type: ignore[attr-defined]
                                entity_id=str(record.id),  # type: ignore[attr-defined]
                                table_name=self.table_name,
                                field_name=field_name,
                                content=content,
                                provider="openai",  # Default provider
                                model="text-embedding-3-small",  # Default model
                            )
                            await self.db.embedding_worker.queue_task(task)

                logger.debug(f"Queued {len(records_list) * len(embeddable_fields)} embedding tasks")

        # Return single item or list to match input type
        return records_list[0] if is_single else records_list

    async def get_by_id(self, record_id: str, tenant_id: str | None = None) -> T | None:
        """
        Get a single record by ID.

        Args:
            record_id: Record identifier
            tenant_id: Optional tenant identifier (deprecated, not used for filtering)

        Returns:
            Model instance or None if not found
        """
        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, returning None for {self.model_class.__name__} get")
            return None

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

        # Note: tenant_id filtering removed - use user_id for access control instead
        query = f"""
            SELECT * FROM {self.table_name}
            WHERE id = $1 AND deleted_at IS NULL
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query, record_id)

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

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

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
        result = await self.upsert(record)
        # upsert with single record returns single record
        return result  # type: ignore[return-value]

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

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

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

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

        sql, params = build_count(self.table_name, filters)

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)

        return row[0] if row else 0

    async def find_paginated(
        self,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 50,
        order_by: str = "created_at DESC",
        partition_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Find records with page-based pagination using CTE with ROW_NUMBER().

        Uses a CTE with ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) for
        efficient pagination with total count in a single query.

        Args:
            filters: Dict of field -> value filters (AND-ed together)
            page: Page number (1-indexed)
            page_size: Number of records per page
            order_by: ORDER BY clause for row numbering (default: "created_at DESC")
            partition_by: Optional field to partition by (e.g., "user_id").
                         If None, uses global row numbering.

        Returns:
            Dict containing:
            - data: List of model instances for the page
            - total: Total count of records matching filters
            - page: Current page number
            - page_size: Records per page
            - total_pages: Total number of pages
            - has_next: Whether there are more pages
            - has_previous: Whether there are previous pages

        Example:
            result = await repo.find_paginated(
                {"tenant_id": "acme", "user_id": "alice"},
                page=2,
                page_size=20,
                order_by="created_at DESC",
                partition_by="user_id"
            )
            # result = {
            #     "data": [...],
            #     "total": 150,
            #     "page": 2,
            #     "page_size": 20,
            #     "total_pages": 8,
            #     "has_next": True,
            #     "has_previous": True
            # }
        """
        if not settings.postgres.enabled or not self.db:
            logger.debug(f"Postgres disabled, returning empty {self.model_class.__name__} pagination")
            return {
                "data": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0,
                "has_next": False,
                "has_previous": False,
            }

        # Ensure connection
        if not self.db.pool:
            await self.db.connect()

        # Type guard: ensure pool is not None after connect
        if not self.db.pool:
            raise RuntimeError("Failed to establish database connection")

        # Build WHERE clause from filters
        where_conditions = ["deleted_at IS NULL"]
        params: list[Any] = []
        param_idx = 1

        for field, value in filters.items():
            where_conditions.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        where_clause = " AND ".join(where_conditions)

        # Build PARTITION BY clause
        partition_clause = f"PARTITION BY {partition_by}" if partition_by else ""

        # Build the CTE query with ROW_NUMBER() and COUNT() window functions
        # This gives us pagination + total count in a single query
        sql = f"""
        WITH numbered AS (
            SELECT *,
                   ROW_NUMBER() OVER ({partition_clause} ORDER BY {order_by}) as _row_num,
                   COUNT(*) OVER ({partition_clause}) as _total_count
            FROM {self.table_name}
            WHERE {where_clause}
        )
        SELECT * FROM numbered
        WHERE _row_num > ${param_idx} AND _row_num <= ${param_idx + 1}
        ORDER BY _row_num
        """

        # Calculate row range for the page
        start_row = (page - 1) * page_size
        end_row = page * page_size
        params.extend([start_row, end_row])

        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        # Extract total from first row (all rows have the same _total_count)
        total = rows[0]["_total_count"] if rows else 0

        # Remove internal columns and convert to models
        data = []
        for row in rows:
            row_dict = dict(row)
            row_dict.pop("_row_num", None)
            row_dict.pop("_total_count", None)
            data.append(self.model_class.model_validate(row_dict))

        # Calculate pagination metadata
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        }
