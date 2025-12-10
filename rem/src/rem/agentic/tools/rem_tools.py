"""
REM tools for agent execution (CLI and API compatible).

These tools work in both CLI and API contexts by initializing services on-demand.
They wrap the service layer directly, not MCP tools.

Core tables (always available):
- resources: Documents, content chunks, artifacts
- moments: Temporal narratives extracted from resources (usually user-specific)
- ontologies: Domain entities with semantic links for further lookups (like a wiki)

Other tables (may vary by deployment):
- users, sessions, messages, files, schemas, feedbacks

Note: Not all tables are populated in all systems. Use FUZZY or SEARCH
to discover what data exists before assuming specific tables have content.
"""

from typing import Any, Literal, cast

from loguru import logger

from ...models.core import (
    FuzzyParameters,
    LookupParameters,
    QueryType,
    RemQuery,
    SearchParameters,
    SQLParameters,
    TraverseParameters,
)
from ...services.content import ContentService
from ...services.postgres import get_postgres_service
from ...services.rem import RemService


# Service cache for reuse within agent execution
_service_cache: dict[str, Any] = {}


async def _get_rem_service() -> RemService:
    """Get or create RemService instance."""
    if "rem_service" not in _service_cache:
        db = get_postgres_service()
        if not db:
            raise RuntimeError("PostgreSQL is disabled. Cannot use REM service.")

        await db.connect()
        _service_cache["postgres"] = db
        _service_cache["rem_service"] = RemService(postgres_service=db)
        logger.debug("Initialized RemService for agent tools")
    return cast(RemService, _service_cache["rem_service"])


async def search_rem_tool(
    query_type: Literal["lookup", "fuzzy", "search", "sql", "traverse"],
    user_id: str,
    # LOOKUP parameters
    entity_key: str | None = None,
    # FUZZY parameters
    query_text: str | None = None,
    threshold: float = 0.7,
    # SEARCH parameters
    table: str | None = None,
    limit: int = 20,
    # SQL parameters
    sql_query: str | None = None,
    # TRAVERSE parameters
    initial_query: str | None = None,
    edge_types: list[str] | None = None,
    depth: int = 1,
) -> dict[str, Any]:
    """
    Execute REM queries for entity lookup, semantic search, and graph traversal.

    This tool works in both CLI and API contexts by initializing services on-demand.

    Args:
        query_type: Type of query (lookup, fuzzy, search, sql, traverse)
        user_id: User identifier for data scoping
        entity_key: Entity key for LOOKUP (e.g., "Sarah Chen")
        query_text: Search text for FUZZY or SEARCH
        threshold: Similarity threshold for FUZZY (0.0-1.0)
        table: Target table for SEARCH (resources, moments, users, etc.)
        limit: Max results for SEARCH
        sql_query: SQL query string for SQL type
        initial_query: Starting entity for TRAVERSE
        edge_types: Edge types to follow for TRAVERSE
        depth: Traversal depth for TRAVERSE

    Returns:
        Dict with query results and metadata
    """
    try:
        rem_service = await _get_rem_service()

        # Build RemQuery based on query_type
        if query_type == "lookup":
            if not entity_key:
                return {"status": "error", "error": "entity_key required for LOOKUP"}

            query = RemQuery(
                query_type=QueryType.LOOKUP,
                parameters=LookupParameters(
                    key=entity_key,
                    user_id=user_id,
                ),
                user_id=user_id,
            )

        elif query_type == "fuzzy":
            if not query_text:
                return {"status": "error", "error": "query_text required for FUZZY"}

            query = RemQuery(
                query_type=QueryType.FUZZY,
                parameters=FuzzyParameters(
                    query_text=query_text,
                    threshold=threshold,
                    limit=limit, # Implied parameter
                ),
                user_id=user_id,
            )

        elif query_type == "search":
            if not query_text:
                return {"status": "error", "error": "query_text required for SEARCH"}
            if not table:
                return {"status": "error", "error": "table required for SEARCH"}

            query = RemQuery(
                query_type=QueryType.SEARCH,
                parameters=SearchParameters(
                    query_text=query_text,
                    table_name=table,
                    limit=limit,
                ),
                user_id=user_id,
            )

        elif query_type == "sql":
            if not sql_query:
                return {"status": "error", "error": "sql_query required for SQL"}
            
            if not table:
                 return {"status": "error", "error": "table required for SQL queries"}

            query = RemQuery(
                query_type=QueryType.SQL,
                parameters=SQLParameters(
                    table_name=table,
                    where_clause=sql_query,
                    limit=limit, # SQLParams accepts limit
                ),
                user_id=user_id,
            )

        elif query_type == "traverse":
            if not initial_query:
                return {"status": "error", "error": "initial_query required for TRAVERSE"}

            query = RemQuery(
                query_type=QueryType.TRAVERSE,
                parameters=TraverseParameters(
                    initial_query=initial_query,
                    edge_types=edge_types or [],
                    max_depth=depth,
                ),
                user_id=user_id,
            )

        else:
            return {"status": "error", "error": f"Unknown query_type: {query_type}"}

        # Execute query
        logger.debug(f"Executing REM query: {query_type} for user {user_id}")
        result = await rem_service.execute_query(query)

        logger.debug(f"Query completed: {query_type}")
        return {
            "status": "success",
            "query_type": query_type,
            "results": result,
        }

    except Exception as e:
        logger.error(f"search_rem_tool failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


async def ingest_file_tool(
    file_uri: str,
    user_id: str,
    category: str | None = None,
    tags: list[str] | None = None,
    is_local_server: bool = True,  # CLI is always local
) -> dict[str, Any]:
    """
    Ingest file into REM (read + store + parse + chunk + embed).

    This tool works in both CLI and API contexts.

    Args:
        file_uri: File location (local path, s3:// URI, or http(s):// URL)
        user_id: User identifier for data scoping
        category: Optional category (document, code, audio, etc.)
        tags: Optional tags for file
        is_local_server: True if running as local CLI (default)

    Returns:
        Dict with file_id, processing_status, resources_created, etc.
    """
    try:
        content_service = ContentService()
        result = await content_service.ingest_file(
            file_uri=file_uri,
            user_id=user_id,
            category=category,
            tags=tags,
            is_local_server=is_local_server,
        )

        logger.debug(
            f"File ingestion complete: {result['file_name']} "
            f"(status: {result['processing_status']}, "
            f"resources: {result['resources_created']})"
        )

        return {
            "status": "success",
            **result,
        }

    except Exception as e:
        logger.error(f"ingest_file_tool failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }
