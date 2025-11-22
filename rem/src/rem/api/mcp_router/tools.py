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
- parse_and_ingest_file: Full ingestion pipeline (read + store + process)

**ARCHITECTURE - File Ingestion Code Paths**:

Three different entry points for file processing:

1. **CLI: `rem process uri <file>`** (cli/commands/process.py)
   - READ-ONLY: No file storage, no database writes
   - Uses: ContentService.process_uri() directly
   - Returns: Extracted content to stdout
   - Use case: Testing file parsing, one-off content extraction

2. **MCP: `parse_and_ingest_file`** (this file, line 455)
   - FULL PIPELINE: Read → Store → Process → Create Resources
   - Uses: Inline file I/O (DUPLICATED from FileSystemService)
   - Creates: File entity + Resource chunks in database
   - Storage: ~/.rem/fs/{tenant_id}/files/{id}/{name} or S3
   - Use case: LLM-driven file ingestion via MCP protocol

3. **Worker: SQS File Processor** (workers/sqs_file_processor.py)
   - BACKGROUND: Processes files from S3 event queue
   - Uses: FileSystemService + ContentService
   - Creates: Resource chunks from existing File entities
   - Use case: Async processing of uploaded files

**SHARED CODE**:
- ContentService: File parsing (PDF, Markdown, etc.) - SHARED by all paths
- FileSystemService: File I/O (read/write S3, local) - SHOULD be shared

**CODE DUPLICATION WARNING**:
parse_and_ingest_file (line 455) duplicates FileSystemService logic.
See inline TODO comments for refactoring plan.
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
    plan_mode: bool = False,
) -> dict[str, Any]:
    """
    Convert natural language question to REM query and optionally execute it.

    Uses REM Query Agent (LLM) to interpret user questions and generate
    appropriate REM queries. Auto-executes if confidence >= 0.7.

    Args:
        natural_query: Natural language question (e.g., "Who is Sarah?")
        tenant_id: Tenant identifier for scoping
        llm_model: Optional LLM model override
        plan_mode: If True, hints agent to use TRAVERSE with depth=0 for edge analysis
                   without full traversal (useful for multi-turn exploration)

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

        >>> # Plan mode - analyze edges without traversal
        >>> result = await ask_rem(
        ...     "What are Sarah's connections?",
        ...     tenant_id="acme",
        ...     plan_mode=True
        ... )
        >>> print(result["query_output"]["query_type"])
        "TRAVERSE"
        >>> print(result["query_output"]["parameters"]["max_depth"])
        0
    """
    if not _rem_service:
        raise RuntimeError("RemService not initialized. Call init_services() first.")

    # Modify query with plan mode hint if requested
    query_with_hint = natural_query
    if plan_mode:
        query_with_hint = (
            f"{natural_query}\n\n"
            "HINT: Use TRAVERSE query with max_depth=0 (PLAN mode) to analyze edges "
            "without full traversal. This is useful for understanding what relationships "
            "exist before deciding which paths to explore."
        )

    result = await _rem_service.ask_rem(
        natural_query=query_with_hint,
        tenant_id=tenant_id,
        llm_model=llm_model,
    )

    logger.info(
        f"ask_rem executed: '{natural_query}' (plan_mode={plan_mode}) "
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


async def parse_and_ingest_file(
    file_uri: str,
    tenant_id: str,
    user_id: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    is_local_server: bool = False,
) -> dict[str, Any]:
    """
    Parse and ingest file into REM, creating searchable resources.

    **ARCHITECTURE - CENTRALIZED INGESTION**:
    This MCP tool delegates to ContentService.ingest_file() which provides the
    complete ingestion pipeline:

    1. **Read**: File from local/S3/HTTP (via FileSystemService)
    2. **Store**: To tenant-scoped internal storage (~/.rem/fs/ or S3)
    3. **Parse**: Extract content, metadata, tables, images (parsing state)
    4. **Chunk**: Semantic chunking with tiktoken for embeddings
    5. **Embed**: Create Resource chunks with vector embeddings

    **PARSING STATE - The Innovation**:
    Files (PDF, WAV, DOCX) → Rich parsing state:
    - **Markdown**: Structured text with hierarchy preserved
    - **Tables**: Extracted as CSV for structured queries
    - **Images**: Saved for multimodal RAG
    - **Metadata**: Provenance tracking (parser used, settings, timestamps)

    This enables agents to deeply understand documents beyond simple text.

    **CLIENT ABSTRACTION**: Clients don't worry about:
    - Storage backend selection (S3 vs local)
    - File parser selection (PDF vs DOCX)
    - Chunking strategy (semantic vs fixed-size)
    - Embedding generation (batching, retry logic)

    Just call this tool and get searchable resources.

    **PERMISSION CHECK**: Remote MCP servers cannot read local files (security).
    The `is_local_server` parameter is checked by ContentService.ingest_file().

    **DEDUPLICATION NOTE**: This is the ONLY place file ingestion logic exists.
    CLI commands use ContentService.process_uri() for read-only extraction.
    Workers use ContentService.process_and_save() for existing files.
    This tool uses ContentService.ingest_file() for full pipeline.

    Args:
        file_uri: File location - local path, s3:// URI, or http(s):// URL
        tenant_id: Tenant identifier for data isolation
        user_id: Optional user ownership
        category: Optional category (document, code, agent, etc.)
        tags: Optional tags for file
        is_local_server: True if running as local/stdio MCP server

    Returns:
        Dict with:
        - file_id: Created file UUID
        - file_name: Original filename
        - storage_uri: Internal storage URI (s3:// or file://)
        - internal_key: S3 key or filesystem path
        - size_bytes: File size
        - content_type: MIME type
        - source_uri: Original file location
        - source_type: "local", "s3", or "url"
        - processing_status: "completed" or "failed"
        - resources_created: Number of Resource chunks created
        - parsing_metadata: Rich parsing state details
        - message: Human-readable status message

    Raises:
        PermissionError: If remote server tries to read local file
        FileNotFoundError: If source file doesn't exist
        RuntimeError: If storage or processing fails

    Example:
        >>> # Local file (local server only)
        >>> result = await parse_and_ingest_file(
        ...     file_uri="/Users/me/contract.pdf",
        ...     tenant_id="acme-corp",
        ...     category="legal",
        ...     is_local_server=True
        ... )
        >>> print(f"Created {result['resources_created']} searchable chunks")

        >>> # S3 URI (all servers)
        >>> result = await parse_and_ingest_file(
        ...     file_uri="s3://bucket/docs/report.pdf",
        ...     tenant_id="acme-corp"
        ... )

        >>> # HTTP URL (all servers)
        >>> result = await parse_and_ingest_file(
        ...     file_uri="https://example.com/whitepaper.pdf",
        ...     tenant_id="acme-corp"
        ... )
    """
    from ...services.content import ContentService

    # Delegate to ContentService for centralized ingestion
    content_service = ContentService()
    result = await content_service.ingest_file(
        file_uri=file_uri,
        tenant_id=tenant_id,
        user_id=user_id,
        category=category,
        tags=tags,
        is_local_server=is_local_server,
    )

    logger.info(
        f"MCP ingestion complete: {result['file_name']} "
        f"(status: {result['processing_status']}, "
        f"resources: {result['resources_created']})"
    )

    return result
