"""
REM Query Service - REM dialect implementation.

REM Dialect Operations:
1. SELECT/INSERT/UPDATE/WITH - Raw SQL queries (automatically detected)
2. SEARCH <text> [FROM <table>] [LIMIT <n>] - Vector similarity search
3. LOOKUP <key> [IN <table>] - Exact KV store lookup
4. FUZZY <text> [IN <table>] [THRESHOLD <n>] - Trigram fuzzy search
5. TRAVERSE <entity> <direction> [DEPTH <n>] - Graph traversal

Examples:
- SELECT * FROM resources WHERE tenant_id = 'acme-corp'
- SEARCH "getting started" FROM resources LIMIT 5
- LOOKUP "docs://getting-started.md" IN resources
- FUZZY "getting start" IN resources THRESHOLD 0.3
- TRAVERSE res:123 OUTBOUND DEPTH 2

Note: Any query not starting with a REM keyword is treated as raw SQL.
Blocked for safety: DROP, DELETE, TRUNCATE, ALTER (destructive operations).
"""

import re
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel

from ...settings import settings
from ...utils.embeddings import generate_embeddings


class REMQueryResult(BaseModel):
    """Result from REM query execution."""

    operation: str
    results: list[dict[str, Any]]
    count: int
    metadata: dict[str, Any] = {}


class REMQueryService:
    """
    REM Query Service - Executes REM dialect queries.

    Parses SQL-like REM dialect and delegates to REMQueryExecutor.
    """

    def __init__(self, postgres_service: Any):
        """
        Initialize REM query service.

        Args:
            postgres_service: PostgresService instance
        """
        self.pg = postgres_service

        # Delegate PostgreSQL function calls to shared executor
        from .executor import REMQueryExecutor
        self.executor = REMQueryExecutor(postgres_service)

        logger.info("Initialized REMQueryService")

    async def execute(self, query: str, user_id: Optional[str] = None) -> REMQueryResult:
        """
        Execute REM dialect query.

        Args:
            query: REM query string
            user_id: Optional user filter

        Returns:
            REMQueryResult with results and metadata

        Raises:
            ValueError: If query syntax is invalid
        """
        query = query.strip()
        logger.info(f"Executing REM query: {query}")

        # Parse operation - check REM keywords first
        query_upper = query.upper()
        if query_upper.startswith("SQL "):
            return await self._execute_sql(query[4:].strip(), user_id)
        elif query_upper.startswith("SEARCH "):
            return await self._execute_search(query[7:].strip(), user_id)
        elif query_upper.startswith("LOOKUP "):
            return await self._execute_lookup(query[7:].strip(), user_id)
        elif query_upper.startswith("FUZZY LOOKUP ") or query_upper.startswith("FUZZY "):
            # Support both "FUZZY LOOKUP" and "FUZZY"
            prefix_len = 13 if query_upper.startswith("FUZZY LOOKUP ") else 6
            return await self._execute_fuzzy_lookup(query[prefix_len:].strip(), user_id)
        elif query_upper.startswith("TRAVERSE "):
            return await self._execute_traverse(query[9:].strip(), user_id)
        else:
            # If not a REM keyword, treat as raw SQL (SELECT, INSERT, UPDATE, DELETE, etc.)
            return await self._execute_sql(query, user_id)

    async def _execute_sql(self, query: str, user_id: Optional[str]) -> REMQueryResult:
        """
        Execute raw SQL query.

        Args:
            query: SQL query string
            user_id: Optional user filter

        Returns:
            Query results
        """
        logger.debug(f"Executing SQL: {query}")

        results = await self.executor.execute_sql(query)

        return REMQueryResult(
            operation="SQL",
            results=results,
            count=len(results),
            metadata={"query": query},
        )

    async def _execute_search(self, query: str, user_id: Optional[str]) -> REMQueryResult:
        """
        Execute vector similarity SEARCH using rem_search() DB function.

        Syntax: SEARCH "<text>" [FROM <table>] [LIMIT <n>]

        Args:
            query: Search query string
            user_id: Optional user filter

        Returns:
            Similar entities ranked by cosine similarity

        Example:
            SEARCH "getting started" FROM resources LIMIT 5

        Note:
            Requires embedding generation for search_text. Currently returns zero
            vector - integrate with OpenAI/Anthropic embedding API for production use.
        """
        match = re.match(
            r'"([^"]+)"(?:\s+FROM\s+(\w+))?(?:\s+LIMIT\s+(\d+))?',
            query,
            re.IGNORECASE,
        )

        if not match:
            raise ValueError(f"Invalid SEARCH syntax: {query}")

        search_text = match.group(1)
        table_name = match.group(2) or "resources"
        limit = int(match.group(3)) if match.group(3) else 10

        logger.debug(
            f"SEARCH: text='{search_text}', table={table_name}, limit={limit}"
        )

        # Generate embedding for search query
        provider_str = f"{settings.llm.embedding_provider}:{settings.llm.embedding_model}"
        embeddings_result = generate_embeddings(provider_str, [search_text])
        # We passed a list, so result is list[list[float]], extract first element
        query_embedding: list[float] = embeddings_result[0]  # type: ignore[assignment]

        # Delegate to executor
        results = await self.executor.execute_search(
            query_embedding=query_embedding,
            table_name=table_name,
            field_name="content",
            provider=settings.llm.embedding_provider,
            min_similarity=0.0,
            limit=limit,
            user_id=user_id,
        )

        return REMQueryResult(
            operation="SEARCH",
            results=results,
            count=len(results),
            metadata={
                "search_text": search_text,
                "table": table_name,
                "limit": limit,
            },
        )

    async def _execute_lookup(self, query: str, user_id: Optional[str]) -> REMQueryResult:
        """
        Execute exact KV store LOOKUP using rem_lookup() DB function.

        Syntax: LOOKUP "<key>" [IN <table>]

        Args:
            query: Lookup query string
            user_id: Optional user filter

        Returns:
            Exact matches from KV store (O(1) lookup)

        Example:
            LOOKUP "docs://getting-started.md" IN resources
        """
        match = re.match(r'"([^"]+)"(?:\s+IN\s+(\w+))?', query, re.IGNORECASE)

        if not match:
            raise ValueError(f"Invalid LOOKUP syntax: {query}")

        entity_key = match.group(1)
        entity_type = match.group(2) or None

        logger.debug(f"LOOKUP: key='{entity_key}', type={entity_type}")

        # Delegate to executor
        results = await self.executor.execute_lookup(
            entity_key=entity_key,
            user_id=user_id,
        )

        return REMQueryResult(
            operation="LOOKUP",
            results=results,
            count=len(results),
            metadata={"entity_key": entity_key, "entity_type": entity_type},
        )

    async def _execute_fuzzy_lookup(
        self, query: str, user_id: Optional[str]
    ) -> REMQueryResult:
        """
        Execute fuzzy LOOKUP using rem_fuzzy() DB function with trigram similarity.

        Syntax: FUZZY LOOKUP "<text>" [IN <table>] [THRESHOLD <n>]

        Args:
            query: Fuzzy lookup query string
            user_id: Optional user filter

        Returns:
            Fuzzy matches ranked by similarity

        Example:
            FUZZY LOOKUP "getting start" IN resources THRESHOLD 0.3
        """
        match = re.match(
            r'"([^"]+)"(?:\s+IN\s+(\w+))?(?:\s+THRESHOLD\s+([\d.]+))?',
            query,
            re.IGNORECASE,
        )

        if not match:
            raise ValueError(f"Invalid FUZZY LOOKUP syntax: {query}")

        search_text = match.group(1)
        entity_type = match.group(2) or None
        threshold = float(match.group(3)) if match.group(3) else 0.3

        logger.debug(
            f"FUZZY LOOKUP: text='{search_text}', type={entity_type}, threshold={threshold}"
        )

        # Delegate to executor
        results = await self.executor.execute_fuzzy(
            query_text=search_text,
            user_id=user_id,
            threshold=threshold,
            limit=10,
        )

        return REMQueryResult(
            operation="FUZZY LOOKUP",
            results=results,
            count=len(results),
            metadata={
                "search_text": search_text,
                "entity_type": entity_type,
                "threshold": threshold,
            },
        )

    async def _execute_traverse(self, query: str, user_id: Optional[str]) -> REMQueryResult:
        """
        Execute graph TRAVERSE using rem_traverse() DB function.

        Syntax: TRAVERSE <entity_id_or_key> <direction> [DEPTH <n>] [TYPE <edge_type>]

        Directions: OUTBOUND (currently supported), INBOUND, BOTH
        Edge types: Optional filter (e.g., "references", "related_to")

        Args:
            query: Traverse query string
            user_id: Optional user filter

        Returns:
            Connected entities via graph edges

        Example:
            TRAVERSE "cae28bba-fa2f-5ef3-bde9-def3030db723" OUTBOUND DEPTH 2
            TRAVERSE "docs://getting-started.md" OUTBOUND DEPTH 1 TYPE "references"

        Note:
            Currently only supports OUTBOUND direction. The SQL function follows
            edges from source to target entities.
        """
        match = re.match(
            r'"?([a-f0-9-]+|[^"]+)"?\s+(OUTBOUND|INBOUND|BOTH)(?:\s+DEPTH\s+(\d+))?(?:\s+TYPE\s+"([^"]+)")?',
            query,
            re.IGNORECASE,
        )

        if not match:
            raise ValueError(f"Invalid TRAVERSE syntax: {query}")

        entity_identifier = match.group(1)
        direction = match.group(2).upper()
        depth = int(match.group(3)) if match.group(3) else 1
        edge_type = match.group(4) if match.group(4) else None

        logger.debug(
            f"TRAVERSE: entity={entity_identifier}, direction={direction}, "
            f"depth={depth}, type={edge_type}"
        )

        if direction != "OUTBOUND":
            logger.warning(
                f"Direction {direction} not yet implemented in rem_traverse - only OUTBOUND supported"
            )

        entity_key = entity_identifier
        if re.match(r"^[a-f0-9-]{36}$", entity_identifier):
            lookup_sql = "SELECT entity_key FROM kv_store WHERE entity_id = $1 AND user_id = $2"
            lookup_result = await self.pg.execute(
                lookup_sql, (entity_identifier, user_id)
            )
            if lookup_result:
                entity_key = lookup_result[0]["entity_key"]
            else:
                return REMQueryResult(
                    operation="TRAVERSE",
                    results=[],
                    count=0,
                    metadata={
                        "entity_identifier": entity_identifier,
                        "direction": direction,
                        "depth": depth,
                        "edge_type": edge_type,
                        "error": "Entity not found",
                    },
                )

        # Convert single edge_type to list
        edge_types = [edge_type] if edge_type else None

        # Delegate to executor
        results = await self.executor.execute_traverse(
            start_key=entity_key,
            direction=direction,
            max_depth=depth,
            edge_types=edge_types,
            user_id=user_id,
        )

        return REMQueryResult(
            operation="TRAVERSE",
            results=results,
            count=len(results),
            metadata={
                "entity_identifier": entity_identifier,
                "entity_key": entity_key,
                "direction": direction,
                "depth": depth,
                "edge_type": edge_type,
            },
        )
