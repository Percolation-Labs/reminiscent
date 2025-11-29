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
from .repository import Repository # Moved from inside get_repository


class PostgresService:
    """
    PostgreSQL database service for REM.

    Manages connections, queries, and transactions for CloudNativePG
    with PostgreSQL 18 and pgvector extension.
    """

    def __init__(
        self,
        embedding_worker: Optional[Any] = ...,  # Sentinel for "not provided"
    ):
        """
        Initialize PostgreSQL service.

        Args:
            embedding_worker: Optional EmbeddingWorker for background embedding generation.
                            If not provided (default), auto-creates one.
                            Pass None to explicitly disable.
        """
        from ...settings import settings
        if not settings.postgres.enabled:
            raise RuntimeError("PostgreSQL is not enabled in the settings.")

        self.connection_string = settings.postgres.connection_string
        self.pool_size = settings.postgres.pool_size
        self.pool: Optional[asyncpg.Pool] = None

        # Use global embedding worker singleton
        if embedding_worker is ...:
            from ..embeddings.worker import get_global_embedding_worker
            # Get or create global worker - it lives independently of this service
            self.embedding_worker = get_global_embedding_worker(postgres_service=self)
        else:
            self.embedding_worker = embedding_worker  # type: ignore[assignment]

    async def execute_ddl(self, query: str) -> None:
        """
        Execute SQL DDL query (e.g., CREATE, ALTER, DROP) without returning results.

        Args:
            query: SQL query string
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def execute_script(self, sql_script: str) -> None:
        """
        Execute a multi-statement SQL script.

        This method properly handles SQL files with multiple statements separated
        by semicolons, including complex scripts with DO blocks, CREATE statements,
        and comments.

        Args:
            sql_script: Complete SQL script content
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        # Split script into individual statements
        # This is a simplified approach - for production consider using sqlparse
        statements = []
        current_statement = []
        in_do_block = False

        for line in sql_script.split('\n'):
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith('--'):
                continue

            # Track DO blocks which can contain semicolons
            if stripped.upper().startswith('DO $$') or stripped.upper().startswith('DO $'):
                in_do_block = True

            current_statement.append(line)

            # Check for statement end
            if stripped.endswith('$$;') or stripped.endswith('$;'):
                in_do_block = False
                statements.append('\n'.join(current_statement))
                current_statement = []
            elif stripped.endswith(';') and not in_do_block:
                statements.append('\n'.join(current_statement))
                current_statement = []

        # Add any remaining statement
        if current_statement:
            stmt = '\n'.join(current_statement).strip()
            if stmt:
                statements.append(stmt)

        # Execute each statement
        async with self.pool.acquire() as conn:
            for statement in statements:
                stmt = statement.strip()
                if stmt:
                    await conn.execute(stmt)

    def _ensure_pool(self) -> None:
        """
        Ensure database connection pool is established.

        Raises:
            RuntimeError: If pool is not connected

        Usage:
            Internal helper used by all query methods to validate connection state.
        """
        if not self.pool:
            raise RuntimeError("PostgreSQL pool not connected. Call connect() first.")

    def get_repository(self, model_class: Type[BaseModel], table_name: str) -> Repository[BaseModel]:
        """
        Get a repository instance for a given model and table.

        Args:
            model_class: The Pydantic model class for the repository.
            table_name: The name of the database table.

        Returns:
            An instance of the Repository class.
        """
        return Repository(model_class=model_class, table_name=table_name, db=self)

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """
        Initialize connection with custom type codecs.

        Sets up automatic JSONB conversion to/from Python objects.
        """
        import json

        # Set up JSONB codec for automatic conversion
        await conn.set_type_codec(
            'jsonb',
            encoder=json.dumps,
            decoder=json.loads,
            schema='pg_catalog',
            format='text',
        )

    async def connect(self) -> None:
        """Establish database connection pool."""
        logger.debug(f"Connecting to PostgreSQL with pool size {self.pool_size}")
        self.pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=1,
            max_size=self.pool_size,
            init=self._init_connection,  # Configure JSONB codec on each connection
        )
        logger.debug("PostgreSQL connection pool established")

        # Start embedding worker if available
        if self.embedding_worker and hasattr(self.embedding_worker, "start"):
            await self.embedding_worker.start()
            logger.debug("Embedding worker started")

    async def disconnect(self) -> None:
        """Close database connection pool."""
        # DO NOT stop the global embedding worker here!
        # It's shared across multiple service instances and processes background tasks
        # The worker will be stopped explicitly when the application shuts down

        if self.pool:
            logger.debug("Closing PostgreSQL connection pool")
            await self.pool.close()
            self.pool = None
            logger.debug("PostgreSQL connection pool closed")

    async def execute(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dicts
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            if params:
                rows = await conn.fetch(query, *params)
            else:
                rows = await conn.fetch(query)

            return [dict(row) for row in rows]

    async def fetch(self, query: str, *params) -> list[asyncpg.Record]:
        """
        Fetch multiple rows from database.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            List of asyncpg.Record objects
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *params)

    async def fetchrow(self, query: str, *params) -> Optional[asyncpg.Record]:
        """
        Fetch single row from database.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            asyncpg.Record or None if no rows found
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *params)

    async def fetchval(self, query: str, *params) -> Any:
        """
        Fetch single value from database.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            Single value or None if no rows found
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    def transaction(self):
        """
        Create a database transaction context manager.

        Returns:
            Transaction object with bound connection for executing queries within a transaction

        Usage:
            async with postgres_service.transaction() as txn:
                await txn.execute("INSERT ...")
                await txn.execute("UPDATE ...")

        Note:
            The transaction object has the same query methods as PostgresService
            (execute, fetch, fetchrow, fetchval) but executes them on a single
            connection within a transaction.
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _transaction_context():
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Yield a transaction wrapper that provides query methods
                    yield _TransactionContext(conn)

        return _transaction_context()

    async def execute_many(
        self,
        query: str,
        params_list: list[tuple],
    ) -> None:
        """
        Execute SQL query with multiple parameter sets.

        Args:
            query: SQL query string
            params_list: List of parameter tuples
        """
        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

        async with self.pool.acquire() as conn:
            await conn.executemany(query, params_list)

    async def upsert(
        self,
        record: BaseModel,
        model: Type[BaseModel],
        table_name: str,
        entity_key_field: str = "name",
        embeddable_fields: list[str] | None = None,
        generate_embeddings: bool = False,
    ) -> BaseModel:
        """
        Upsert a single record.

        Convenience wrapper around batch_upsert for single records.

        Args:
            record: Pydantic model instance
            model: Pydantic model class
            table_name: Database table name
            entity_key_field: Field name to use as KV store key (default: "name")
            embeddable_fields: List of fields to generate embeddings for
            generate_embeddings: Whether to generate embeddings (default: False)

        Returns:
            The upserted record

        Example:
            >>> from rem.models.entities import Message
            >>> message = Message(content="Hello", session_id="abc", tenant_id="acme")
            >>> result = await pg.upsert(
            ...     record=message,
            ...     model=Message,
            ...     table_name="messages"
            ... )
        """
        await self.batch_upsert(
            records=[record],
            model=model,
            table_name=table_name,
            entity_key_field=entity_key_field,
            embeddable_fields=embeddable_fields,
            generate_embeddings=generate_embeddings,
        )
        return record

    async def upsert_entity(
        self,
        entity: BaseModel,
        entity_key: str,
        tenant_id: str,
        embeddable_fields: list[str] | None = None,
        generate_embeddings: bool = False,
    ) -> BaseModel:
        """
        Upsert an entity using explicit entity_key.

        This is a convenience method that auto-detects table name from model.

        Args:
            entity: Pydantic model instance
            entity_key: Value to use for KV store key (not field name)
            tenant_id: Tenant identifier
            embeddable_fields: List of fields to generate embeddings for
            generate_embeddings: Whether to generate embeddings (default: False)

        Returns:
            The upserted entity

        Example:
            >>> from rem.models.entities import Ontology
            >>> ontology = Ontology(name="cv-parser", tenant_id="acme", ...)
            >>> result = await pg.upsert_entity(
            ...     entity=ontology,
            ...     entity_key=ontology.name,
            ...     tenant_id=ontology.tenant_id
            ... )
        """
        # Auto-detect table name from model class
        model_class = type(entity)
        table_name = f"{model_class.__name__.lower()}s"

        await self.batch_upsert(
            records=[entity],
            model=model_class,
            table_name=table_name,
            entity_key_field="name",  # Default field name for entity key
            embeddable_fields=embeddable_fields,
            generate_embeddings=generate_embeddings,
        )
        return entity

    async def batch_upsert(
        self,
        records: list[BaseModel | dict],
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
            records: List of Pydantic model instances or dicts (will be validated against model)
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
            >>> # Or with dicts
            >>> resources = [{"name": "doc1", "content": "...", "tenant_id": "acme"}]
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
                "ids": [],
            }

        logger.info(
            f"Batch upserting {len(records)} records to {table_name} "
            f"(entity_key: {entity_key_field}, embeddings: {generate_embeddings})"
        )

        # Convert dict records to Pydantic models
        pydantic_records = []
        for record in records:
            if isinstance(record, dict):
                pydantic_records.append(model.model_validate(record))
            else:
                pydantic_records.append(record)

        # Validate records for KV store requirements
        for record in pydantic_records:
            valid, error = validate_record_for_kv_store(record, entity_key_field)
            if not valid:
                logger.warning(f"Record validation failed: {error} - {record}")

        # Prepare records (using pydantic_records after conversion)
        field_names = list(model.model_fields.keys())
        prepared_records = [
            prepare_record_for_upsert(r, model, entity_key_field) for r in pydantic_records
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
                "ids": [],
            }

        # Process in batches
        total_upserted = 0
        total_embeddings = 0
        batch_count = 0
        upserted_ids = []  # Track IDs of upserted records

        self._ensure_pool()
        assert self.pool is not None  # Type guard for mypy

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
                        # Track the ID
                        if "id" in record:
                            upserted_ids.append(record["id"])
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

                        from ...settings import settings

                        task = EmbeddingTask(
                            task_id=f"{entity_id}:{field_name}",
                            entity_id=str(entity_id),
                            table_name=table_name,
                            field_name=field_name,
                            content=content,
                            provider=settings.llm.embedding_provider,
                            model=settings.llm.embedding_model,
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
            "ids": upserted_ids,  # List of IDs for upserted records
        }

    async def vector_search(
        self,
        table_name: str,
        embedding: list[float],
        limit: int = 10,
        min_similarity: float = 0.3,
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
        self,
        entity_id: str,
        edges: list[dict[str, Any]],
        merge: bool = True,
    ) -> None:
        """
        Update graph edges for an entity.

        Args:
            entity_id: Entity UUID
            edges: List of InlineEdge dicts
            merge: If True, merge with existing edges; if False, replace
        """
        raise NotImplementedError("Graph edge updates not yet implemented")


class _TransactionContext:
    """
    Transaction context with bound connection.

    Provides the same query interface as PostgresService but executes
    all queries on a single connection within a transaction.

    This is safer than method swapping and provides explicit transaction scope.
    """

    def __init__(self, conn: asyncpg.Connection):
        """
        Initialize transaction context.

        Args:
            conn: Database connection bound to this transaction
        """
        self.conn = conn

    async def execute(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute SQL query within transaction.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dicts
        """
        if params:
            rows = await self.conn.fetch(query, *params)
        else:
            rows = await self.conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch(self, query: str, *params) -> list[asyncpg.Record]:
        """
        Fetch multiple rows within transaction.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            List of asyncpg.Record objects
        """
        return await self.conn.fetch(query, *params)

    async def fetchrow(self, query: str, *params) -> Optional[asyncpg.Record]:
        """
        Fetch single row within transaction.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            asyncpg.Record or None if no rows found
        """
        return await self.conn.fetchrow(query, *params)

    async def fetchval(self, query: str, *params) -> Any:
        """
        Fetch single value within transaction.

        Args:
            query: SQL query string
            *params: Query parameters

        Returns:
            Single value or None if no rows found
        """
        return await self.conn.fetchval(query, *params)