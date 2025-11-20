"""
PostgresService - CloudNativePG database operations.

Provides connection management and query execution for PostgreSQL 18
with pgvector extension running on CloudNativePG.

Key Features:
- Connection pooling
- Tenant isolation
- Vector similarity search
- JSONB operations for graph edges
- Transaction management

CloudNativePG Integration:
- Uses PostgreSQL 18 with pgvector extension
- Extension loaded via ImageVolume pattern (immutable)
- extension_control_path configured for pgvector
- Streaming replication for HA
- Backup to S3 via Barman

Performance Considerations:
- GIN indexes on JSONB fields (related_entities, graph_edges)
- Vector indexes (IVF/HNSW) for similarity search
- Tenant-scoped queries for isolation
- Connection pooling for concurrency
"""

from typing import Any, Optional, Type

import asyncpg
from loguru import logger
from pydantic import BaseModel

from ...utils.batch_ops import (
    batch_iterator,
    build_upsert_statement,
    prepare_record_for_upsert,
    validate_record_for_kv_store,
)
from ...utils.sql_types import get_sql_type


class PostgresService:
    """
    PostgreSQL database service for REM.

    Manages connections, queries, and transactions for CloudNativePG
    with PostgreSQL 18 and pgvector extension.
    """

    def __init__(
        self,
        connection_string: str,
        pool_size: int = 10,
        embedding_worker: Optional[Any] = None,
    ):
        """
        Initialize PostgreSQL service.

        Args:
            connection_string: PostgreSQL connection string
            pool_size: Connection pool size
            embedding_worker: Optional EmbeddingWorker for background embedding generation
        """
        self.connection_string = connection_string
        self.pool_size = pool_size
        self.pool: Optional[asyncpg.Pool] = None

        # Auto-create embedding worker if not provided
        if embedding_worker is None:
            from ..embeddings import EmbeddingWorker
            self.embedding_worker = EmbeddingWorker(postgres_service=self)
        else:
            self.embedding_worker = embedding_worker

    async def connect(self) -> None:
        """Establish database connection pool."""
        logger.info(f"Connecting to PostgreSQL with pool size {self.pool_size}")
        self.pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=1,
            max_size=self.pool_size,
        )
        logger.info("PostgreSQL connection pool established")

        # Start embedding worker if available
        if self.embedding_worker and hasattr(self.embedding_worker, "start"):
            await self.embedding_worker.start()
            logger.info("Embedding worker started")

    async def disconnect(self) -> None:
        """Close database connection pool."""
        # Stop embedding worker first
        if self.embedding_worker and hasattr(self.embedding_worker, "stop"):
            await self.embedding_worker.stop()
            logger.info("Embedding worker stopped")

        if self.pool:
            logger.info("Closing PostgreSQL connection pool")
            await self.pool.close()
            self.pool = None
            logger.info("PostgreSQL connection pool closed")

    async def execute(
        self, query: str, params: Optional[tuple] = None
    ) -> list[dict[str, Any]]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dicts
        """
        if not self.pool:
            raise RuntimeError("PostgreSQL pool not connected. Call connect() first.")

        async with self.pool.acquire() as conn:
            if params:
                rows = await conn.fetch(query, *params)
            else:
                rows = await conn.fetch(query)

            return [dict(row) for row in rows]

    async def execute_many(
        self, query: str, params_list: list[tuple]
    ) -> None:
        """
        Execute SQL query with multiple parameter sets.

        Args:
            query: SQL query string
            params_list: List of parameter tuples
        """
        if not self.pool:
            raise RuntimeError("PostgreSQL pool not connected. Call connect() first.")

        async with self.pool.acquire() as conn:
            await conn.executemany(query, params_list)

    async def batch_upsert(
        self,
        records: list[BaseModel],
        model: Type[BaseModel],
        table_name: str,
        entity_key_field: str = "name",
        embeddable_fields: list[str] | None = None,
        batch_size: int = 100,
        generate_embeddings: bool = False,
    ) -> dict[str, Any]:
        """
        Batch upsert records with KV store population and optional embedding generation.

        KV Store Integration:
        - Triggers automatically populate kv_store on INSERT/UPDATE
        - Unique on (tenant_id, entity_key) where entity_key comes from entity_key_field
        - User can store same key in multiple tables (different source_table_id)
        - Supports user_id scoping (user_id can be NULL for shared entities)

        Embedding Generation:
        - Queues embedding tasks for background processing via EmbeddingWorker
        - Upserts to embeddings_<table> with unique (entity_id, field_name, provider)
        - Returns immediately without waiting for embeddings (async processing)

        Args:
            records: List of Pydantic model instances
            model: Pydantic model class
            table_name: Database table name
            entity_key_field: Field name to use as KV store key (default: "name")
            embeddable_fields: List of fields to generate embeddings for (auto-detected if None)
            batch_size: Number of records per batch
            generate_embeddings: Whether to generate embeddings (default: False)

        Returns:
            Dict with:
            - upserted_count: Number of records upserted
            - kv_store_populated: Number of KV store entries (via triggers)
            - embeddings_generated: Number of embeddings generated
            - batches_processed: Number of batches processed

        Example:
            >>> from rem.models.entities import Resource
            >>> resources = [Resource(name="doc1", content="...", tenant_id="acme")]
            >>> result = await pg.batch_upsert(
            ...     records=resources,
            ...     model=Resource,
            ...     table_name="resources",
            ...     entity_key_field="name",
            ...     generate_embeddings=True
            ... )

        Design Notes:
            - Delegates SQL generation to utils.sql_types
            - Uses utils.batch_ops for batching and preparation
            - KV store population happens via database triggers (no explicit code)
            - Embedding generation is batched for efficiency
        """
        if not records:
            logger.warning("No records to upsert")
            return {
                "upserted_count": 0,
                "kv_store_populated": 0,
                "embeddings_generated": 0,
                "batches_processed": 0,
            }

        logger.info(
            f"Batch upserting {len(records)} records to {table_name} "
            f"(entity_key: {entity_key_field}, embeddings: {generate_embeddings})"
        )

        # Validate records for KV store requirements
        for record in records:
            valid, error = validate_record_for_kv_store(record, entity_key_field)
            if not valid:
                logger.warning(f"Record validation failed: {error} - {record}")

        # Prepare records
        field_names = list(model.model_fields.keys())
        prepared_records = [
            prepare_record_for_upsert(r, model, entity_key_field) for r in records
        ]

        # Build upsert statement (use actual field names from prepared records)
        if prepared_records:
            actual_fields = list(prepared_records[0].keys())
            upsert_sql = build_upsert_statement(
                table_name, actual_fields, conflict_column="id"
            )
        else:
            logger.warning("No prepared records to upsert")
            return {
                "upserted_count": 0,
                "kv_store_populated": 0,
                "embeddings_generated": 0,
                "batches_processed": 0,
            }

        # Process in batches
        total_upserted = 0
        total_embeddings = 0
        batch_count = 0

        if not self.pool:
            raise RuntimeError("PostgreSQL pool not connected. Call connect() first.")

        for batch in batch_iterator(prepared_records, batch_size):
            batch_count += 1
            logger.debug(f"Processing batch {batch_count} with {len(batch)} records")

            # Execute batch upsert
            async with self.pool.acquire() as conn:
                for record in batch:
                    # Extract values in the same order as actual_fields
                    values = tuple(record.get(field) for field in actual_fields)

                    try:
                        await conn.execute(upsert_sql, *values)
                        total_upserted += 1
                    except Exception as e:
                        logger.error(f"Failed to upsert record: {e}")
                        logger.debug(f"Record: {record}")
                        logger.debug(f"SQL: {upsert_sql}")
                        logger.debug(f"Values: {values}")
                        raise

            # KV store population happens automatically via triggers
            # No explicit code needed - triggers handle it

            # Queue embedding tasks for background processing
            if generate_embeddings and embeddable_fields and self.embedding_worker:
                for record_dict in batch:
                    entity_id = record_dict.get("id")
                    if not entity_id:
                        continue

                    for field_name in embeddable_fields:
                        content = record_dict.get(field_name)
                        if not content or not isinstance(content, str):
                            continue

                        # Queue embedding task (non-blocking)
                        from ..embeddings import EmbeddingTask

                        task = EmbeddingTask(
                            task_id=f"{entity_id}:{field_name}",
                            entity_id=str(entity_id),
                            table_name=table_name,
                            field_name=field_name,
                            content=content,
                            provider="openai",
                            model="text-embedding-3-small",
                        )

                        await self.embedding_worker.queue_task(task)
                        total_embeddings += 1

                logger.debug(
                    f"Queued {total_embeddings} embedding tasks for background processing"
                )

        logger.info(
            f"Batch upsert complete: {total_upserted} records, "
            f"{total_embeddings} embeddings, {batch_count} batches"
        )

        return {
            "upserted_count": total_upserted,
            "kv_store_populated": total_upserted,  # Triggers populate 1:1
            "embeddings_generated": total_embeddings,
            "batches_processed": batch_count,
        }

    async def vector_search(
        self,
        table_name: str,
        embedding: list[float],
        limit: int = 10,
        min_similarity: float = 0.7,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Perform vector similarity search using pgvector.

        Args:
            table_name: Table to search (resources, moments, etc.)
            embedding: Query embedding vector
            limit: Maximum results
            min_similarity: Minimum cosine similarity threshold
            tenant_id: Optional tenant filter

        Returns:
            List of similar entities with similarity scores

        Note:
            Use rem_search() SQL function for vector search instead.
        """
        raise NotImplementedError(
            "Use REMQueryService.execute('SEARCH ...') for vector similarity search"
        )

    async def jsonb_query(
        self,
        table_name: str,
        jsonb_field: str,
        query_path: str,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Query JSONB field with path expression.

        Args:
            table_name: Table to query
            jsonb_field: JSONB column name
            query_path: JSONB path query
            tenant_id: Optional tenant filter

        Returns:
            Matching rows
        """
        raise NotImplementedError("JSONB path queries not yet implemented")

    async def create_resource(self, resource: dict[str, Any]) -> str:
        """
        Create new resource in database.

        Args:
            resource: Resource data dict

        Returns:
            Created resource ID

        Note:
            Use batch_upsert() method for creating resources.
        """
        raise NotImplementedError("Use batch_upsert() for creating resources")

    async def create_moment(self, moment: dict[str, Any]) -> str:
        """
        Create new moment in database.

        Args:
            moment: Moment data dict

        Returns:
            Created moment ID

        Note:
            Use batch_upsert() method for creating moments.
        """
        raise NotImplementedError("Use batch_upsert() for creating moments")

    async def update_graph_edges(
        self, entity_id: str, edges: list[dict[str, Any]], merge: bool = True
    ) -> None:
        """
        Update graph edges for an entity.

        Args:
            entity_id: Entity UUID
            edges: List of InlineEdge dicts
            merge: If True, merge with existing edges; if False, replace
        """
        raise NotImplementedError("Graph edge updates not yet implemented")
