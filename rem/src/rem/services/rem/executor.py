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

import asyncio
from collections import defaultdict
from typing import Any, Optional, cast
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
            SELECT entity_type, data
            FROM rem_lookup($1, $2, $3)
        """

        results = await self.db.execute(sql, (entity_key, user_id, user_id))
        # Extract JSONB records from the data column and add aliases
        entities = []
        for row in results:
            entity = dict(row["data"])
            # Add entity_key as alias for name (for backward compat with tests)
            if "name" in entity:
                entity["entity_key"] = entity["name"]
            # Add entity_id as alias for id (for backward compat with tests)
            if "id" in entity:
                entity["entity_id"] = entity["id"]
            entities.append(entity)
        logger.debug(f"LOOKUP '{entity_key}': {len(entities)} results")
        return entities

    async def execute_fetch(
        self,
        entity_keys: list[str],
        entity_types: list[str],
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute rem_fetch() PostgreSQL function.

        Fetches full entity records (all columns) from multiple tables by entity keys.
        Groups by table internally, fetches all records, returns unified JSONB result set.
        Returns complete entities, not just KV store metadata.

        Args:
            entity_keys: List of entity keys to fetch
            entity_types: Parallel list of entity types (table names)
            user_id: Optional user filter

        Returns:
            List of full entity records as dicts with entity_key, entity_type, and entity_record
        """
        if not entity_keys:
            return []

        # Build JSONB structure: {"resources": ["key1", "key2"], "moments": ["key3"]}
        import json
        entities_by_table: dict[str, list[str]] = {}
        for key, table in zip(entity_keys, entity_types):
            if table not in entities_by_table:
                entities_by_table[table] = []
            entities_by_table[table].append(key)

        entities_json = json.dumps(entities_by_table)

        sql = """
            SELECT entity_key, entity_type, entity_record
            FROM rem_fetch($1::jsonb, $2)
        """

        results = await self.db.execute(sql, (entities_json, user_id))

        logger.debug(
            f"FETCH: {len(results)}/{len(entity_keys)} records fetched from {len(set(entity_types))} tables"
        )
        return cast(list[dict[str, Any]], results)

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
            SELECT entity_type, data, similarity_score
            FROM rem_fuzzy($1, $2, $3, $4, $5)
        """

        results = await self.db.execute(
            sql, (query_text, user_id, threshold, limit, user_id)
        )
        # Extract JSONB records and add similarity_score + entity_key alias
        entities = []
        for row in results:
            entity = dict(row["data"])
            entity["similarity_score"] = row["similarity_score"]
            # Add entity_key as alias for name (for backward compat)
            if "name" in entity:
                entity["entity_key"] = entity["name"]
            entities.append(entity)
        logger.debug(f"FUZZY '{query_text}': {len(entities)} results (threshold={threshold})")
        return entities

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
            SELECT entity_type, similarity_score, data
            FROM rem_search($1::vector(1536), $2, $3, $4, $5, $6, $7, $8)
        """

        results = await self.db.execute(
            sql,
            (
                embedding_str,
                table_name,
                field_name,
                user_id,  # tenant_id (backward compat)
                provider,
                min_similarity,
                limit,
                user_id,  # user_id
            ),
        )
        # Extract JSONB records and add similarity_score + entity_key alias
        entities = []
        for row in results:
            entity = dict(row["data"])
            entity["similarity_score"] = row["similarity_score"]
            entity["entity_type"] = row["entity_type"]
            # Add entity_key as alias for name (for backward compat)
            if "name" in entity:
                entity["entity_key"] = entity["name"]
            # Add distance as alias for similarity_score (for backward compat)
            # Note: similarity_score is cosine similarity (higher = more similar)
            # distance is inverse (lower = more similar), so: distance = 1 - similarity_score
            entity["distance"] = 1.0 - row["similarity_score"]
            entities.append(entity)
        logger.debug(
            f"SEARCH in {table_name}.{field_name}: {len(entities)} results (similarity≥{min_similarity})"
        )
        return entities

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

        # Note: rem_traverse signature is (entity_key, tenant_id, user_id, max_depth, rel_type, keys_only)
        # tenant_id is for backward compat, set to user_id
        # direction parameter is not used by the current PostgreSQL function
        # edge_types is single value, not array
        edge_type_filter = edge_types[0] if edge_types else None

        sql = """
            SELECT depth, entity_key, entity_type, entity_id, rel_type, rel_weight, path, entity_record
            FROM rem_traverse($1, $2, $3, $4, $5, $6)
        """

        results = await self.db.execute(
            sql, (start_key, user_id, user_id, max_depth, edge_type_filter, False)
        )
        # Add edge_type alias for rel_type (backward compat)
        processed_results = []
        for row in results:
            result = dict(row)
            if "rel_type" in result:
                result["edge_type"] = result["rel_type"]
            processed_results.append(result)

        logger.debug(
            f"TRAVERSE from '{start_key}' (depth={max_depth}): {len(processed_results)} results"
        )
        return processed_results

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
        return cast(list[dict[str, Any]], results)
