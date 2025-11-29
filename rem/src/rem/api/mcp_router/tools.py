"""
MCP Tools for REM operations.

Tools are functions that LLMs can call to interact with the REM system.
Each tool is decorated with @mcp.tool() and registered with the FastMCP server.

Design Pattern:
- Tools receive parameters from LLM
- Tools delegate to RemService or ContentService
- Tools return structured results
- Tools handle errors gracefully with informative messages

Available Tools:
- search_rem: Execute REM queries (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
- ask_rem_agent: Natural language to REM query conversion via agent
- ingest_into_rem: Full file ingestion pipeline (read + store + parse + chunk)
- read_resource: Access MCP resources (for Claude Desktop compatibility)
"""

from functools import wraps
from typing import Any, Callable, Literal, cast

from loguru import logger

from ...agentic.context import AgentContext
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


# Service cache for FastAPI lifespan initialization
_service_cache: dict[str, Any] = {}


def init_services(postgres_service: PostgresService, rem_service: RemService):
    """
    Initialize service instances for MCP tools.

    Called during FastAPI lifespan startup.

    Args:
        postgres_service: PostgresService instance
        rem_service: RemService instance
    """
    _service_cache["postgres"] = postgres_service
    _service_cache["rem"] = rem_service
    logger.debug("MCP tools initialized with service instances")


async def get_rem_service() -> RemService:
    """
    Get or create RemService instance (lazy initialization).

    Returns cached instance if available, otherwise creates new one.
    Thread-safe for async usage.
    """
    if "rem" in _service_cache:
        return cast(RemService, _service_cache["rem"])

    # Lazy initialization for in-process/CLI usage
    from ...services.postgres import get_postgres_service

    postgres_service = get_postgres_service()
    if not postgres_service:
        raise RuntimeError("PostgreSQL is disabled. Cannot use REM service.")
        
    await postgres_service.connect()
    rem_service = RemService(postgres_service=postgres_service)

    _service_cache["postgres"] = postgres_service
    _service_cache["rem"] = rem_service

    logger.debug("MCP tools: lazy initialized services")
    return rem_service


def mcp_tool_error_handler(func: Callable) -> Callable:
    """
    Decorator for consistent MCP tool error handling.

    Wraps tool functions to:
    - Log errors with full context
    - Return standardized error responses
    - Prevent exceptions from bubbling to LLM

    Usage:
        @mcp_tool_error_handler
        async def my_tool(...) -> dict[str, Any]:
            # Pure business logic - no try/except needed
            result = await service.do_work()
            return {"data": result}

    Returns:
        {"status": "success", **result} on success
        {"status": "error", "error": str(e)} on failure
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> dict[str, Any]:
        try:
            result = await func(*args, **kwargs)
            # If result already has status, return as-is
            if isinstance(result, dict) and "status" in result:
                return result
            # Otherwise wrap in success response
            return {"status": "success", **result}
        except Exception as e:
            logger.error(f"{func.__name__} failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "tool": func.__name__,
            }
    return wrapper


@mcp_tool_error_handler
async def search_rem(
    query_type: Literal["lookup", "fuzzy", "search", "sql", "traverse"],
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
    # Optional context override (defaults to authenticated user)
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute REM queries for entity lookup, semantic search, and graph traversal.

    REM supports multiple query types for different retrieval patterns:

    **LOOKUP** - O(1) entity resolution by natural language key:
    - Fast exact match across all tables
    - Uses indexed label_vector for instant retrieval
    - Example: LOOKUP "Sarah Chen" returns all entities named "Sarah Chen"

    **FUZZY** - Fuzzy text matching with similarity threshold:
    - Finds partial matches and typos
    - Example: FUZZY "sara" threshold=0.7 finds "Sarah Chen", "Sara Martinez"

    **SEARCH** - Semantic vector search (table-specific):
    - Finds conceptually similar entities
    - Example: SEARCH "database migration" table=resources returns related documents

    **SQL** - Direct SQL queries for structured data:
    - Full PostgreSQL query power (scoped to table)
    - Example: SQL "role = 'engineer'" (WHERE clause only)

    **TRAVERSE** - Graph traversal following relationships:
    - Explores entity neighborhood via graph edges
    - Supports depth control and edge type filtering
    - Example: TRAVERSE "Sarah Chen" edge_types=["manages", "reports_to"] depth=2

    Args:
        query_type: Type of query (lookup, fuzzy, search, sql, traverse)
        entity_key: Entity key for LOOKUP (e.g., "Sarah Chen")
        query_text: Search text for FUZZY or SEARCH
        threshold: Similarity threshold for FUZZY (0.0-1.0)
        table: Target table for SEARCH (resources, moments, users, etc.)
        limit: Max results for SEARCH
        sql_query: SQL WHERE clause for SQL type (e.g. "id = '123'")
        initial_query: Starting entity for TRAVERSE
        edge_types: Edge types to follow for TRAVERSE (e.g., ["manages", "reports_to"])
        depth: Traversal depth for TRAVERSE (0=plan only, 1-5=actual traversal)
        user_id: Optional user identifier (defaults to authenticated user or "default")

    Returns:
        Dict with query results, metadata, and execution info

    Examples:
        # Lookup entity (uses authenticated user context)
        search_rem(
            query_type="lookup",
            entity_key="Sarah Chen"
        )

        # Semantic search
        search_rem(
            query_type="search",
            query_text="database migration",
            table="resources",
            limit=10
        )

        # SQL query (WHERE clause only)
        search_rem(
            query_type="sql",
            table="resources",
            sql_query="category = 'document'"
        )

        # Graph traversal
        search_rem(
            query_type="traverse",
            initial_query="Sarah Chen",
            edge_types=["manages", "reports_to"],
            depth=2
        )
    """
    # Get RemService instance (lazy initialization)
    rem_service = await get_rem_service()

    # Get user_id from context if not provided
    # TODO: Extract from authenticated session context when auth is enabled
    user_id = AgentContext.get_user_id_or_default(user_id, source="search_rem")

    # Normalize query_type to lowercase for case-insensitive REM dialect
    query_type = cast(Literal["lookup", "fuzzy", "search", "sql", "traverse"], query_type.lower())

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
                limit=limit, # Limit was missing in original logic but likely intended
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
        
        # SQLParameters requires table_name. If not provided, we cannot execute.
        # Assuming sql_query is just the WHERE clause based on RemService implementation,
        # OR if table is provided we use it.
        if not table:
             return {"status": "error", "error": "table required for SQL queries (parameter: table)"}

        query = RemQuery(
            query_type=QueryType.SQL,
            parameters=SQLParameters(
                table_name=table,
                where_clause=sql_query,
                limit=limit,
            ),
            user_id=user_id,
        )

    elif query_type == "traverse":
        if not initial_query:
            return {
                "status": "error",
                "error": "initial_query required for TRAVERSE",
            }

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

    # Execute query (errors handled by decorator)
    logger.info(f"Executing REM query: {query_type} for user {user_id}")
    result = await rem_service.execute_query(query)

    logger.info(f"Query completed successfully: {query_type}")
    return {
        "query_type": query_type,
        "results": result,
    }


@mcp_tool_error_handler
async def ask_rem_agent(
    query: str,
    agent_schema: str = "ask_rem",
    agent_version: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Ask REM using natural language via agent-driven query conversion.

    This tool converts natural language questions into optimized REM queries
    using an agent that understands the REM query language and schema.

    The agent can perform multi-turn reasoning and iterated retrieval:
    1. Initial exploration (LOOKUP/FUZZY to find entities)
    2. Semantic search (SEARCH for related content)
    3. Graph traversal (TRAVERSE to explore relationships)
    4. Synthesis (combine results into final answer)

    Args:
        query: Natural language question or task
        agent_schema: Agent schema name (default: "ask_rem")
        agent_version: Optional agent version (default: latest)
        user_id: Optional user identifier (defaults to authenticated user or "default")

    Returns:
        Dict with:
        - status: "success" or "error"
        - response: Agent's natural language response
        - query_output: Structured query results (if available)
        - queries_executed: List of REM queries executed
        - metadata: Agent execution metadata

    Examples:
        # Simple question (uses authenticated user context)
        ask_rem_agent(
            query="Who is Sarah Chen?"
        )

        # Complex multi-step question
        ask_rem_agent(
            query="What are the key findings from last week's sprint retrospective?"
        )

        # Graph exploration
        ask_rem_agent(
            query="Show me Sarah's reporting chain and their recent projects"
        )
    """
    # Get user_id from context if not provided
    # TODO: Extract from authenticated session context when auth is enabled
    user_id = AgentContext.get_user_id_or_default(user_id, source="ask_rem_agent")

    from ...agentic import create_agent
    from ...utils.schema_loader import load_agent_schema

    # Create agent context
    context = AgentContext(
        user_id=user_id,
        tenant_id=user_id,  # Set tenant_id to user_id for backward compat
        default_model=settings.llm.default_model,
    )

    # Load agent schema
    try:
        schema = load_agent_schema(agent_schema)
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"Agent schema not found: {agent_schema}",
        }

    # Create agent
    agent_runtime = await create_agent(
        context=context,
        agent_schema_override=schema,
    )

    # Run agent (errors handled by decorator)
    logger.debug(f"Running ask_rem agent for query: {query[:100]}...")
    result = await agent_runtime.run(query)

    # Extract output
    from rem.agentic.serialization import serialize_agent_result
    query_output = serialize_agent_result(result.output)

    logger.debug("Agent execution completed successfully")

    return {
        "response": str(result.output),
        "query_output": query_output,
        "natural_query": query,
    }


@mcp_tool_error_handler
async def ingest_into_rem(
    file_uri: str,
    category: str | None = None,
    tags: list[str] | None = None,
    is_local_server: bool = False,
    user_id: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    """
    Ingest file into REM, creating searchable resources and embeddings.

    This tool provides the complete file ingestion pipeline:
    1. **Read**: File from local/S3/HTTP
    2. **Store**: To user-scoped internal storage
    3. **Parse**: Extract content, metadata, tables, images
    4. **Chunk**: Semantic chunking for embeddings
    5. **Embed**: Create Resource chunks with vector embeddings

    Supported file types:
    - Documents: PDF, DOCX, TXT, Markdown
    - Code: Python, JavaScript, TypeScript, etc.
    - Data: CSV, JSON, YAML
    - Audio: WAV, MP3 (transcription)

    **Security**: Remote MCP servers cannot read local files. Only local/stdio
    MCP servers can access local filesystem paths.

    Args:
        file_uri: File location (local path, s3:// URI, or http(s):// URL)
        category: Optional category (document, code, audio, etc.)
        tags: Optional tags for file
        is_local_server: True if running as local/stdio MCP server
        user_id: Optional user identifier (defaults to authenticated user or "default")
        resource_type: Optional resource type for storing chunks (case-insensitive).
            Supports flexible naming:
            - "resource", "resources", "Resource" → Resource (default)
            - "domain-resource", "domain_resource", "DomainResource",
              "domain-resources" → DomainResource (curated internal knowledge)

    Returns:
        Dict with:
        - status: "success" or "error"
        - file_id: Created file UUID
        - file_name: Original filename
        - storage_uri: Internal storage URI
        - processing_status: "completed" or "failed"
        - resources_created: Number of Resource chunks created
        - content: Parsed file content (markdown format) if completed
        - message: Human-readable status message

    Examples:
        # Ingest local file (local server only, uses authenticated user context)
        ingest_into_rem(
            file_uri="/Users/me/contract.pdf",
            category="legal",
            is_local_server=True
        )

        # Ingest from S3
        ingest_into_rem(
            file_uri="s3://bucket/docs/report.pdf"
        )

        # Ingest from HTTP
        ingest_into_rem(
            file_uri="https://example.com/whitepaper.pdf",
            tags=["research", "whitepaper"]
        )

        # Ingest as curated domain knowledge
        ingest_into_rem(
            file_uri="s3://bucket/internal/procedures.pdf",
            resource_type="domain-resource",
            category="procedures"
        )
    """
    from ...services.content import ContentService

    # Get user_id from context if not provided
    # TODO: Extract from authenticated session context when auth is enabled
    user_id = AgentContext.get_user_id_or_default(user_id, source="ingest_into_rem")

    # Delegate to ContentService for centralized ingestion (errors handled by decorator)
    content_service = ContentService()
    result = await content_service.ingest_file(
        file_uri=file_uri,
        user_id=user_id,
        category=category,
        tags=tags,
        is_local_server=is_local_server,
        resource_type=resource_type,
    )

    logger.debug(
        f"MCP ingestion complete: {result['file_name']} "
        f"(status: {result['processing_status']}, "
        f"resources: {result['resources_created']})"
    )

    return result


@mcp_tool_error_handler
async def read_resource(uri: str) -> dict[str, Any]:
    """
    Read an MCP resource by URI.

    This tool provides automatic access to MCP resources in Claude Desktop.
    Resources contain authoritative, up-to-date reference data.

    **IMPORTANT**: This tool enables Claude Desktop to automatically access
    resources based on query relevance. While FastMCP correctly exposes resources
    via standard MCP resource endpoints, Claude Desktop currently requires manual
    resource attachment. This tool bridges that gap by exposing resource access
    as a tool, which Claude Desktop WILL automatically invoke.

    **Available Resources:**

    Agent Schemas:
    • rem://schemas - List all agent schemas
    • rem://schema/{name} - Get specific schema definition
    • rem://schema/{name}/{version} - Get specific version

    System Status:
    • rem://status - System health and statistics

    Args:
        uri: Resource URI (e.g., "rem://schemas", "rem://schema/ask_rem")

    Returns:
        Dict with:
        - status: "success" or "error"
        - uri: Original URI
        - data: Resource data (format depends on resource type)

    Examples:
        # List all schemas
        read_resource(uri="rem://schemas")

        # Get specific schema
        read_resource(uri="rem://schema/ask_rem")

        # Get schema version
        read_resource(uri="rem://schema/ask_rem/v1.0.0")

        # Check system status
        read_resource(uri="rem://status")
    """
    logger.debug(f"Reading resource: {uri}")

    # Import here to avoid circular dependency
    from .resources import load_resource

    # Load resource using the existing resource handler (errors handled by decorator)
    result = await load_resource(uri)

    logger.debug(f"Resource loaded successfully: {uri}")

    # If result is already a dict, return it
    if isinstance(result, dict):
        return {
            "uri": uri,
            "data": result,
        }

    # If result is a string (JSON), parse it
    import json

    try:
        data = json.loads(result)
        return {
            "uri": uri,
            "data": data,
        }
    except json.JSONDecodeError:
        # Return as plain text if not JSON
        return {
            "uri": uri,
            "data": {"content": result},
        }


async def register_metadata(
    confidence: float | None = None,
    references: list[str] | None = None,
    sources: list[str] | None = None,
    flags: list[str] | None = None,
    # Risk assessment fields (used by mental health agents like Siggy)
    risk_level: str | None = None,
    risk_score: int | None = None,
    risk_reasoning: str | None = None,
    recommended_action: str | None = None,
    # Generic extension - any additional key-value pairs
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Register response metadata to be emitted as an SSE MetadataEvent.

    Call this tool BEFORE generating your final response to provide structured
    metadata that will be sent to the client alongside your natural language output.
    This allows you to stream conversational responses while still providing
    machine-readable confidence scores, references, and other metadata.

    **Design Pattern**: Agents can call this once before their final response to
    register metadata that the streaming layer will emit as a MetadataEvent.
    This decouples structured metadata from the response format.

    Args:
        confidence: Confidence score (0.0-1.0) for the response quality.
            - 0.9-1.0: High confidence, answer is well-supported
            - 0.7-0.9: Medium confidence, some uncertainty
            - 0.5-0.7: Low confidence, significant gaps
            - <0.5: Very uncertain, may need clarification
        references: List of reference identifiers (file paths, document IDs,
            entity labels) that support the response.
        sources: List of source descriptions (e.g., "REM database",
            "search results", "user context").
        flags: Optional flags for the response (e.g., "needs_review",
            "uncertain", "incomplete", "crisis_alert").

        risk_level: Risk level indicator (e.g., "green", "orange", "red").
            Used by mental health agents for C-SSRS style assessment.
        risk_score: Numeric risk score (e.g., 0-6 for C-SSRS).
        risk_reasoning: Brief explanation of risk assessment.
        recommended_action: Suggested next steps based on assessment.

        extra: Dict of arbitrary additional metadata. Use this for any
            domain-specific fields not covered by the standard parameters.
            Example: {"topics_detected": ["anxiety", "sleep"], "session_count": 5}

    Returns:
        Dict with:
        - status: "success"
        - _metadata_event: True (marker for streaming layer)
        - All provided fields merged into response

    Examples:
        # High confidence answer with references
        register_metadata(
            confidence=0.95,
            references=["sarah-chen", "q3-report-2024"],
            sources=["REM database lookup"]
        )

        # Mental health risk assessment (Siggy-style)
        register_metadata(
            confidence=0.9,
            risk_level="green",
            risk_score=0,
            risk_reasoning="No risk indicators detected in message",
            sources=["mental_health_resources"]
        )

        # Orange risk with recommended action
        register_metadata(
            risk_level="orange",
            risk_score=2,
            risk_reasoning="Passive ideation detected - 'feeling hopeless'",
            recommended_action="Schedule care team check-in within 24-48 hours",
            flags=["care_team_alert"]
        )

        # Custom domain-specific metadata
        register_metadata(
            confidence=0.8,
            extra={
                "topics_detected": ["medication", "side_effects"],
                "drug_mentioned": "sertraline",
                "sentiment": "concerned"
            }
        )
    """
    logger.debug(
        f"Registering metadata: confidence={confidence}, "
        f"risk_level={risk_level}, refs={len(references or [])}, "
        f"sources={len(sources or [])}"
    )

    result = {
        "status": "success",
        "_metadata_event": True,  # Marker for streaming layer
        "confidence": confidence,
        "references": references,
        "sources": sources,
        "flags": flags,
    }

    # Add risk assessment fields if provided
    if risk_level is not None:
        result["risk_level"] = risk_level
    if risk_score is not None:
        result["risk_score"] = risk_score
    if risk_reasoning is not None:
        result["risk_reasoning"] = risk_reasoning
    if recommended_action is not None:
        result["recommended_action"] = recommended_action

    # Merge any extra fields
    if extra:
        result["extra"] = extra

    return result
