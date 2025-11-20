"""
MCP Tools for REM operations.

Tools are functions that LLMs can call to interact with the REM system.
Each tool is decorated with @mcp.tool() and registered with the FastMCP server.

Design Pattern:
- Tools receive parameters from LLM
- Tools delegate to RemService or PostgresService
- Tools return structured results
- Tools handle errors gracefully with informative messages

Available Tools:
- rem_query: Execute REM queries (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
- ask_rem: Natural language to REM query conversion
- create_resource: Create new resource with content
- create_moment: Create temporal narrative
- update_graph_edges: Add/update entity graph edges
- upload_file: Upload file to S3 (tenant-scoped)
- download_file: Download file from S3
"""

from typing import Any, Literal

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
from ...services.postgres import PostgresService
from ...services.rem import RemService
from ...settings import settings


# Global service instances (initialized in FastAPI lifespan)
_postgres_service: PostgresService | None = None
_rem_service: RemService | None = None


def init_services(postgres_service: PostgresService, rem_service: RemService):
    """
    Initialize global service instances for MCP tools.

    Called during FastAPI lifespan startup.

    Args:
        postgres_service: PostgresService instance
        rem_service: RemService instance
    """
    global _postgres_service, _rem_service
    _postgres_service = postgres_service
    _rem_service = rem_service
    logger.info("MCP tools initialized with service instances")


async def rem_query(
    query_type: Literal["lookup", "fuzzy", "search", "sql", "traverse"],
    tenant_id: str,
    # LOOKUP parameters
    entity_key: str | None = None,
    user_id: str | None = None,
    # FUZZY parameters
    query_text: str | None = None,
    threshold: float = 0.7,
    limit: int = 10,
    # SEARCH parameters
    table_name: str | None = None,
    field_name: str | None = None,
    provider: str | None = None,
    min_similarity: float = 0.7,
    # SQL parameters
    where_clause: str | None = None,
    # TRAVERSE parameters
    start_key: str | None = None,
    max_depth: int = 1,
    rel_type: str | None = None,
) -> dict[str, Any]:
    """
    Execute REM query with specified type and parameters.

    REM Query Types:
    - LOOKUP: O(1) entity resolution (requires: entity_key)
    - FUZZY: Fuzzy text matching (requires: query_text)
    - SEARCH: Semantic vector search (requires: query_text, table_name)
    - SQL: Direct SQL queries (requires: table_name, optional: where_clause)
    - TRAVERSE: Graph traversal (requires: start_key, optional: rel_type, max_depth)

    Args:
        query_type: Type of query to execute
        tenant_id: Tenant identifier for scoping
        entity_key: Key for LOOKUP queries
        user_id: Optional user scoping
        query_text: Query text for FUZZY/SEARCH
        threshold: Similarity threshold for FUZZY
        limit: Result limit
        table_name: Table name for SEARCH/SQL
        field_name: Field name for SEARCH (defaults to 'content')
        provider: Embedding provider for SEARCH
        min_similarity: Minimum similarity for SEARCH
        where_clause: WHERE clause for SQL
        start_key: Starting entity for TRAVERSE
        max_depth: Maximum traversal depth
        rel_type: Relationship type filter for TRAVERSE

    Returns:
        Query results with metadata

    Raises:
        ValueError: If required parameters are missing
        QueryExecutionError: If query execution fails
    """
    if not _rem_service:
        raise RuntimeError("RemService not initialized. Call init_services() first.")

    # Build parameters based on query type
    query_type_enum = QueryType(query_type.upper())

    if query_type_enum == QueryType.LOOKUP:
        if not entity_key:
            raise ValueError("LOOKUP requires entity_key parameter")
        parameters = LookupParameters(entity_key=entity_key, user_id=user_id)

    elif query_type_enum == QueryType.FUZZY:
        if not query_text:
            raise ValueError("FUZZY requires query_text parameter")
        parameters = FuzzyParameters(
            query_text=query_text,
            threshold=threshold,
            limit=limit,
            user_id=user_id,
        )

    elif query_type_enum == QueryType.SEARCH:
        if not query_text or not table_name:
            raise ValueError("SEARCH requires query_text and table_name parameters")
        parameters = SearchParameters(
            query_text=query_text,
            table_name=table_name,
            field_name=field_name,
            provider=provider,
            min_similarity=min_similarity,
            limit=limit,
            user_id=user_id,
        )

    elif query_type_enum == QueryType.SQL:
        if not table_name:
            raise ValueError("SQL requires table_name parameter")
        parameters = SQLParameters(
            table_name=table_name,
            where_clause=where_clause,
            limit=limit,
        )

    elif query_type_enum == QueryType.TRAVERSE:
        if not start_key:
            raise ValueError("TRAVERSE requires start_key parameter")
        parameters = TraverseParameters(
            start_key=start_key,
            max_depth=max_depth,
            rel_type=rel_type,
            user_id=user_id,
        )

    else:
        raise ValueError(f"Unknown query type: {query_type}")

    # Execute query
    query = RemQuery(
        query_type=query_type_enum,
        parameters=parameters,
        tenant_id=tenant_id,
    )

    result = await _rem_service.execute_query(query)
    logger.info(f"REM query executed: {query_type} ({result['count']} results)")

    return result


async def ask_rem(
    natural_query: str,
    tenant_id: str,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """
    Convert natural language question to REM query and optionally execute it.

    Uses REM Query Agent (LLM) to interpret user questions and generate
    appropriate REM queries. Auto-executes if confidence >= 0.7.

    Args:
        natural_query: Natural language question (e.g., "Who is Sarah?")
        tenant_id: Tenant identifier for scoping
        llm_model: Optional LLM model override

    Returns:
        Dict with:
        - query_output: REMQueryOutput from agent
        - results: Executed query results (if confidence >= 0.7)
        - warning: Low confidence warning (if confidence < 0.7)

    Example:
        >>> result = await ask_rem("Who is Sarah?", tenant_id="acme")
        >>> print(result["query_output"]["query_type"])
        "LOOKUP"
        >>> print(result["results"]["count"])
        1
    """
    if not _rem_service:
        raise RuntimeError("RemService not initialized. Call init_services() first.")

    result = await _rem_service.ask_rem(
        natural_query=natural_query,
        tenant_id=tenant_id,
        llm_model=llm_model,
    )

    logger.info(
        f"ask_rem executed: '{natural_query}' "
        f"(confidence: {result['query_output']['confidence']})"
    )

    return result


async def create_resource(
    tenant_id: str,
    name: str,
    content: str,
    category: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    generate_embeddings: bool = True,
) -> dict[str, Any]:
    """
    Create new resource in REM system.

    Resources are chunked, embedded content from documents, files, or conversations.

    Args:
        tenant_id: Tenant identifier
        name: Resource name/label
        content: Resource content text
        category: Optional category (document, conversation, etc.)
        user_id: Optional user ownership
        metadata: Optional metadata dict
        generate_embeddings: Whether to generate embeddings (default: True)

    Returns:
        Dict with created resource details

    Example:
        >>> result = await create_resource(
        ...     tenant_id="acme",
        ...     name="api-design-v2",
        ...     content="API design document for v2...",
        ...     category="document"
        ... )
    """
    if not _postgres_service:
        raise RuntimeError(
            "PostgresService not initialized. Call init_services() first."
        )

    from ...models.entities import Resource

    resource = Resource(
        name=name,
        content=content,
        category=category,
        tenant_id=tenant_id,
        user_id=user_id,
        metadata=metadata or {},
    )

    result = await _postgres_service.batch_upsert(
        records=[resource],
        model=Resource,
        table_name="resources",
        entity_key_field="name",
        generate_embeddings=generate_embeddings,
    )

    logger.info(f"Resource created: {name} (tenant: {tenant_id})")

    return {
        "resource_id": str(resource.id),
        "name": name,
        "tenant_id": tenant_id,
        "upserted": result["upserted_count"],
        "embeddings_generated": result["embeddings_generated"],
    }


async def create_moment(
    tenant_id: str,
    name: str,
    moment_type: str,
    summary: str | None = None,
    present_persons: list[dict[str, Any]] | None = None,
    emotion_tags: list[str] | None = None,
    topic_tags: list[str] | None = None,
    source_resource_ids: list[str] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Create new moment (temporal narrative) in REM system.

    Moments are time-bound events that classify and organize resources and entities.

    Args:
        tenant_id: Tenant identifier
        name: Moment name/label
        moment_type: Type (meeting, coding_session, conversation, etc.)
        summary: Natural language summary
        present_persons: List of Person dicts with id, name, role
        emotion_tags: Emotion tags (happy, frustrated, focused, etc.)
        topic_tags: Topic tags (project names, concepts)
        source_resource_ids: Referenced resource IDs
        user_id: Optional user ownership

    Returns:
        Dict with created moment details

    Example:
        >>> result = await create_moment(
        ...     tenant_id="acme",
        ...     name="api-design-meeting-2025-01-15",
        ...     moment_type="meeting",
        ...     summary="Team discussed API v2 design...",
        ...     present_persons=[{"id": "sarah-chen", "name": "Sarah Chen", "role": "lead"}],
        ...     topic_tags=["api-design", "architecture"]
        ... )
    """
    if not _postgres_service:
        raise RuntimeError(
            "PostgresService not initialized. Call init_services() first."
        )

    from ...models.entities import Moment

    moment = Moment(
        name=name,
        moment_type=moment_type,
        summary=summary,
        present_persons=present_persons or [],
        emotion_tags=emotion_tags or [],
        topic_tags=topic_tags or [],
        source_resource_ids=source_resource_ids or [],
        tenant_id=tenant_id,
        user_id=user_id,
    )

    result = await _postgres_service.batch_upsert(
        records=[moment],
        model=Moment,
        table_name="moments",
        entity_key_field="name",
        generate_embeddings=False,  # Moments don't need embeddings
    )

    logger.info(f"Moment created: {name} (tenant: {tenant_id})")

    return {
        "moment_id": str(moment.id),
        "name": name,
        "moment_type": moment_type,
        "tenant_id": tenant_id,
        "upserted": result["upserted_count"],
    }


async def update_graph_edges(
    entity_id: str,
    edges: list[dict[str, Any]],
    merge: bool = True,
) -> dict[str, Any]:
    """
    Update graph edges for an entity.

    Edges use InlineEdge format with human-readable destination labels.

    Args:
        entity_id: Entity UUID
        edges: List of InlineEdge dicts with dst, rel_type, weight, properties
        merge: If True, merge with existing edges; if False, replace

    Returns:
        Dict with update status

    Example:
        >>> result = await update_graph_edges(
        ...     entity_id="uuid-123",
        ...     edges=[
        ...         {
        ...             "dst": "sarah-chen",
        ...             "rel_type": "authored_by",
        ...             "weight": 1.0,
        ...             "properties": {"dst_name": "Sarah Chen", "dst_entity_type": "person"}
        ...         }
        ...     ]
        ... )
    """
    if not _postgres_service:
        raise RuntimeError(
            "PostgresService not initialized. Call init_services() first."
        )

    await _postgres_service.update_graph_edges(
        entity_id=entity_id,
        edges=edges,
        merge=merge,
    )

    logger.info(f"Graph edges updated: {entity_id} ({len(edges)} edges)")

    return {
        "entity_id": entity_id,
        "edges_updated": len(edges),
        "merge": merge,
    }
