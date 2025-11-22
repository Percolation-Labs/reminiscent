"""
REM Query Executor - Shared PostgreSQL function calling layer.

This module provides the single source of truth for executing REM queries
against PostgreSQL functions (rem_lookup, rem_search, rem_fuzzy, rem_traverse).

Both REMQueryService (string-based) and RemService (Pydantic-based) delegate
to these functions to avoid code duplication.

Design:
- One function per query type
- All embedding generation happens here
- Direct PostgreSQL function calls
- Type-safe parameters via Pydantic models or dicts
"""

from typing import Any, Optional
from loguru import logger


class REMQueryExecutor:
    """
    Executor for REM PostgreSQL functions.

    Provides unified backend for both string-based and Pydantic-based query services.
    """

    def __init__(self, postgres_service: Any):
        """
        Initialize query executor.

        Args:
            postgres_service: PostgresService instance
        """
        self.db = postgres_service
        logger.debug("Initialized REMQueryExecutor")

    async def execute_lookup(
        self,
        entity_key: str,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute rem_lookup() PostgreSQL function.

        Args:
            entity_key: Entity key to lookup
            user_id: Optional user filter

        Returns:
            List of entity dicts from KV_STORE
        """
        sql = """
            SELECT entity_key, entity_type, entity_id, tenant_id, user_id, created_at,
                   content_summary, metadata
            FROM rem_lookup($1, $2)
        """

        results = await self.db.execute(sql, (entity_key, user_id))
        logger.debug(f"LOOKUP '{entity_key}': {len(results)} results")
        return results

    async def execute_fuzzy(
        self,
        query_text: str,
        user_id: str | None = None,
        threshold: float = 0.3,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Execute rem_fuzzy() PostgreSQL function.

        Args:
            query_text: Text to fuzzy match
            user_id: Optional user filter
            threshold: Similarity threshold (0.0-1.0)
            limit: Max results

        Returns:
            List of fuzzy-matched entities with similarity_score
        """
        sql = """
            SELECT entity_key, entity_type, entity_id, tenant_id, user_id, created_at,
                   content_summary, metadata, similarity_score
            FROM rem_fuzzy($1, $2, $3, $4)
        """

        results = await self.db.execute(
            sql, (query_text, user_id, threshold, limit)
        )
        logger.debug(f"FUZZY '{query_text}': {len(results)} results (threshold={threshold})")
        return results

    async def execute_search(
        self,
        query_embedding: list[float],
        table_name: str,
        field_name: str,
        provider: str,
        min_similarity: float = 0.7,
        limit: int = 10,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute rem_search() PostgreSQL function.

        Args:
            query_embedding: Embedding vector for query
            table_name: Table to search (resources, moments, users)
            field_name: Field name to search
            provider: Embedding provider (openai, anthropic)
            min_similarity: Minimum cosine similarity
            limit: Max results
            user_id: Optional user filter

        Returns:
            List of similar entities with distance scores
        """
        # Convert embedding to PostgreSQL vector format
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        sql = """
            SELECT entity_key, entity_type, entity_id, distance, content_summary
            FROM rem_search($1::vector(1536), $2, $3, $4, $5, $6, $7)
        """

        results = await self.db.execute(
            sql,
            (
                embedding_str,
                table_name,
                field_name,
                user_id,
                provider,
                min_similarity,
                limit,
            ),
        )
        logger.debug(
            f"SEARCH in {table_name}.{field_name}: {len(results)} results (similarity≥{min_similarity})"
        )
        return results

    async def execute_traverse(
        self,
        start_key: str,
        direction: str,
        max_depth: int,
        edge_types: list[str] | None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute rem_traverse() PostgreSQL function.

        Args:
            start_key: Starting entity key
            direction: OUTBOUND, INBOUND, or BOTH (not used in current function)
            max_depth: Maximum traversal depth
            edge_types: Optional list of edge types to filter
            user_id: Optional user filter

        Returns:
            List of traversed entities with path information
        """
        # Convert edge_types to PostgreSQL array or NULL
        edge_types_sql = None
        if edge_types:
            edge_types_sql = "{" + ",".join(edge_types) + "}"

        # Note: rem_traverse signature is (entity_key, user_id, max_depth, rel_type)
        # direction parameter is not used by the current PostgreSQL function
        sql = """
            SELECT depth, entity_key, entity_type, entity_id, rel_type, rel_weight, path
            FROM rem_traverse($1, $2, $3, $4)
        """

        results = await self.db.execute(
            sql, (start_key, user_id, max_depth, edge_types_sql)
        )
        logger.debug(
            f"TRAVERSE from '{start_key}' (depth={max_depth}): {len(results)} results"
        )
        return results

    async def execute_sql(
        self,
        query: str,
    ) -> list[dict[str, Any]]:
        """
        Execute raw SQL query.

        Args:
            query: SQL query string

        Returns:
            Query results as list of dicts
        """
        results = await self.db.execute(query)
        logger.debug(f"SQL query: {len(results)} results")
        return results
