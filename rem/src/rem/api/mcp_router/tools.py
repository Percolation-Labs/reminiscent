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


async def ingest_file(
    file_uri: str,
    tenant_id: str,
    user_id: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    is_local_server: bool = False,
) -> dict[str, Any]:
    """
    Ingest a file into REM system with synchronous processing.

    This is a transactional operation:
    1. Copy file from source to REM's internal storage (respecting tenant paths)
    2. Process file synchronously via ContentService
    3. Return processing results

    Supports:
    - Local file paths (local MCP servers only)
    - S3 URIs (s3://bucket/key)
    - HTTP/HTTPS URLs (https://example.com/file.pdf)

    Args:
        file_uri: File location - local path, s3:// URI, or http(s):// URL
        tenant_id: Tenant identifier
        user_id: Optional user ownership
        category: Optional category (document, code, agent, etc.)
        tags: Optional tags for file
        is_local_server: True if running as local/stdio MCP server

    Returns:
        Dict with:
        - file_id: Created file UUID
        - file_name: Original filename
        - storage_uri: Internal storage URI (s3:// or file://)
        - size_bytes: File size
        - processing_status: Processing result
        - resources_created: Number of resources created (if processed)
        - schema_stored: True if agent schema was stored

    Example:
        >>> # Local file (local server only)
        >>> result = await ingest_file(
        ...     file_uri="/Users/me/my-agent.yaml",
        ...     tenant_id="acme",
        ...     category="agent",
        ...     is_local_server=True
        ... )
        >>> # Returns: {"file_id": "...", "schema_stored": True, ...}

        >>> # S3 URI (all servers)
        >>> result = await ingest_file(
        ...     file_uri="s3://my-bucket/documents/file.pdf",
        ...     tenant_id="acme"
        ... )

        >>> # HTTP URL (all servers)
        >>> result = await ingest_file(
        ...     file_uri="https://example.com/document.pdf",
        ...     tenant_id="acme"
        ... )
    """
    if not _postgres_service:
        raise RuntimeError(
            "PostgresService not initialized. Call init_services() first."
        )

    from pathlib import Path
    from urllib.parse import urlparse
    from uuid import uuid4

    from ...models.entities import File
    from ...services.content import ContentService
    from ...settings import settings

    # Parse URI to determine source type
    parsed = urlparse(file_uri)

    # Determine source type and validate permissions
    if parsed.scheme in ("http", "https"):
        source_type = "url"
        file_name = Path(parsed.path).name or "downloaded_file"
    elif parsed.scheme == "s3":
        source_type = "s3"
        s3_bucket = parsed.netloc
        s3_source_key = parsed.path.lstrip("/")
        file_name = Path(s3_source_key).name
    elif parsed.scheme == "" or parsed.scheme == "file":
        # Local file path
        if not is_local_server:
            raise PermissionError(
                "Local file paths are only allowed for local MCP servers. "
                "Use s3:// URIs or https:// URLs for remote servers."
            )
        source_type = "local"
        file_path_obj = Path(file_uri.replace("file://", ""))
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_uri}")
        if not file_path_obj.is_file():
            raise ValueError(f"Path is not a file: {file_uri}")
        file_name = file_path_obj.name
    else:
        raise ValueError(
            f"Unsupported URI scheme: {parsed.scheme}. "
            "Supported: local paths (local server only), s3://, http://, https://"
        )

    # Step 1: Read source file content
    if source_type == "local":
        file_content = file_path_obj.read_bytes()
    elif source_type == "url":
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(file_uri) as response:
                response.raise_for_status()
                file_content = await response.read()
    elif source_type == "s3":
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3.endpoint_url,
            aws_access_key_id=settings.s3.access_key_id,
            aws_secret_access_key=settings.s3.secret_access_key,
            region_name=settings.s3.region,
        ) as s3_client:
            try:
                response = await s3_client.get_object(
                    Bucket=s3_bucket,
                    Key=s3_source_key,
                )
                file_content = await response["Body"].read()
            except ClientError as e:
                logger.error(f"S3 download failed: {e}")
                raise RuntimeError(f"S3 download failed: {e}")

    file_size = len(file_content)
    file_id = uuid4()

    # Step 2: Store in REM's internal storage with tenant-scoped path
    # Format: {tenant_id}/files/{file_id}/{file_name}
    internal_key = f"{tenant_id}/files/{file_id}/{file_name}"

    # Determine storage backend (S3 or local filesystem)
    if settings.s3.bucket_name:
        # Production: Use S3
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3.endpoint_url,
            aws_access_key_id=settings.s3.access_key_id,
            aws_secret_access_key=settings.s3.secret_access_key,
            region_name=settings.s3.region,
        ) as s3_client:
            try:
                await s3_client.put_object(
                    Bucket=settings.s3.bucket_name,
                    Key=internal_key,
                    Body=file_content,
                )
                storage_uri = f"s3://{settings.s3.bucket_name}/{internal_key}"
            except ClientError as e:
                logger.error(f"S3 upload failed: {e}")
                raise RuntimeError(f"S3 upload failed: {e}")
    else:
        # Local development: Use ~/.rem/fs/
        from pathlib import Path

        fs_root = Path.home() / ".rem" / "fs"
        fs_root.mkdir(parents=True, exist_ok=True)

        file_path = fs_root / internal_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(file_content)

        storage_uri = f"file://{file_path}"

    # Detect content type
    import mimetypes

    content_type, _ = mimetypes.guess_type(file_name)
    content_type = content_type or "application/octet-stream"

    # Create File entity
    file_entity = File(
        id=file_id,
        tenant_id=tenant_id,
        user_id=user_id,
        name=file_name,
        s3_key=internal_key,
        s3_bucket=settings.s3.bucket_name or "local",
        content_type=content_type,
        size_bytes=file_size,
        metadata={
            "source_uri": file_uri,
            "source_type": source_type,
            "category": category,
            "storage_uri": storage_uri,
        },
        tags=tags or [],
    )

    # Step 3: Process file synchronously via ContentService
    content_service = ContentService(
        file_repo=_postgres_service.get_repository(File, "files"),
        resource_repo=_postgres_service.get_repository(None, "resources"),
    )

    try:
        processing_result = content_service.process_uri(storage_uri)
        processing_status = "completed"
        resources_created = len(processing_result.get("resources", []))
    except Exception as e:
        logger.error(f"File processing failed: {e}", exc_info=True)
        processing_status = "failed"
        resources_created = 0
        processing_result = {"error": str(e)}

    # Check if agent schema was stored
    schema_stored = False
    if category == "agent" or file_name.endswith((".yaml", ".yml", ".json")):
        # TODO: Detect and store agent schemas
        # For now, just flag it for manual processing
        schema_stored = False

    logger.info(
        f"File ingested and processed: {file_name} "
        f"(source: {source_type}, tenant: {tenant_id}, "
        f"size: {file_size} bytes, resources: {resources_created})"
    )

    return {
        "file_id": str(file_id),
        "file_name": file_name,
        "storage_uri": storage_uri,
        "internal_key": internal_key,
        "size_bytes": file_size,
        "content_type": content_type,
        "source_uri": file_uri,
        "source_type": source_type,
        "processing_status": processing_status,
        "resources_created": resources_created,
        "schema_stored": schema_stored,
        "message": f"File ingested and {processing_status}. Created {resources_created} resources.",
    }
