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
- register_metadata: Register response metadata for SSE MetadataEvent
- list_schema: List all schemas (tables, agents) in the database with row counts
- get_schema: Get detailed schema for a table (columns, types, indexes)
"""

import json
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
            # Use %s format to avoid issues with curly braces in error messages
            logger.opt(exception=True).error("{} failed: {}", func.__name__, str(e))
            return {
                "status": "error",
                "error": str(e),
                "tool": func.__name__,
            }
    return wrapper


@mcp_tool_error_handler
async def search_rem(
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Execute a REM query using the REM query dialect.

    **REM Query Syntax:**

    LOOKUP <entity_key>
        Find entity by exact name/key. Searches across all tables.
        Example: LOOKUP phq-9-procedure
        Example: LOOKUP sertraline

    SEARCH <text> IN <table>
        Semantic vector search within a specific table.
        Tables: 'ontologies' (clinical knowledge, procedures, drugs, DSM criteria)
                'resources' (documents, files, user content)
        Example: SEARCH depression IN ontologies
        Example: SEARCH Module F IN ontologies

    FUZZY <text>
        Fuzzy text matching for partial matches and typos.
        Example: FUZZY setraline

    TRAVERSE <start_entity>
        Graph traversal from a starting entity.
        Example: TRAVERSE sarah-chen

    Args:
        query: REM query string (e.g., "LOOKUP phq-9-procedure", "SEARCH depression IN ontologies")
        limit: Maximum results to return (default: 20)

    Returns:
        Dict with query results and metadata. If no results found, includes
        'suggestions' with alternative search strategies.

    Examples:
        search_rem("LOOKUP phq-9-procedure")
        search_rem("SEARCH depression IN ontologies")
        search_rem("SEARCH anxiety treatment IN ontologies", limit=10)
        search_rem("FUZZY setraline")
    """
    # Get RemService instance (lazy initialization)
    rem_service = await get_rem_service()

    # Get user_id from context
    user_id = AgentContext.get_user_id_or_default(None, source="search_rem")

    # Parse the REM query string
    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Empty query. Use REM syntax: LOOKUP <key>, SEARCH <text> IN <table>, FUZZY <text>, or TRAVERSE <entity>",
        }

    query = query.strip()
    parts = query.split(None, 1)  # Split on first whitespace

    if len(parts) < 2:
        return {
            "status": "error",
            "error": f"Invalid query format: '{query}'. Expected: LOOKUP <key>, SEARCH <text> IN <table>, FUZZY <text>, or TRAVERSE <entity>",
        }

    query_type = parts[0].upper()
    remainder = parts[1].strip()

    # Build RemQuery based on query_type
    if query_type == "LOOKUP":
        if not remainder:
            return {
                "status": "error",
                "error": "LOOKUP requires an entity key. Example: LOOKUP phq-9-procedure",
            }

        rem_query = RemQuery(
            query_type=QueryType.LOOKUP,
            parameters=LookupParameters(
                key=remainder,
                user_id=user_id,
            ),
            user_id=user_id,
        )
        table = None  # LOOKUP searches all tables

    elif query_type == "SEARCH":
        # Parse "text IN table" format
        if " IN " in remainder.upper():
            # Find the last " IN " to handle cases like "SEARCH pain IN back IN ontologies"
            in_pos = remainder.upper().rfind(" IN ")
            search_text = remainder[:in_pos].strip()
            table = remainder[in_pos + 4:].strip().lower()
        else:
            return {
                "status": "error",
                "error": f"SEARCH requires table: SEARCH <text> IN <table>. "
                "Use 'ontologies' for clinical knowledge or 'resources' for documents. "
                f"Example: SEARCH {remainder} IN ontologies",
            }

        if not search_text:
            return {
                "status": "error",
                "error": "SEARCH requires search text. Example: SEARCH depression IN ontologies",
            }

        rem_query = RemQuery(
            query_type=QueryType.SEARCH,
            parameters=SearchParameters(
                query_text=search_text,
                table_name=table,
                limit=limit,
            ),
            user_id=user_id,
        )

    elif query_type == "FUZZY":
        if not remainder:
            return {
                "status": "error",
                "error": "FUZZY requires search text. Example: FUZZY setraline",
            }

        rem_query = RemQuery(
            query_type=QueryType.FUZZY,
            parameters=FuzzyParameters(
                query_text=remainder,
                threshold=0.3,  # pg_trgm similarity - 0.3 is reasonable for typo correction
                limit=limit,
            ),
            user_id=user_id,
        )
        table = None

    elif query_type == "TRAVERSE":
        if not remainder:
            return {
                "status": "error",
                "error": "TRAVERSE requires a starting entity. Example: TRAVERSE sarah-chen",
            }

        rem_query = RemQuery(
            query_type=QueryType.TRAVERSE,
            parameters=TraverseParameters(
                initial_query=remainder,
                edge_types=[],
                max_depth=1,
            ),
            user_id=user_id,
        )
        table = None

    else:
        return {
            "status": "error",
            "error": f"Unknown query type: '{query_type}'. Valid types: LOOKUP, SEARCH, FUZZY, TRAVERSE. "
            "Examples: LOOKUP phq-9-procedure, SEARCH depression IN ontologies",
        }

    # Execute query (errors handled by decorator)
    logger.info(f"Executing REM query: {query_type} for user {user_id}")
    result = await rem_service.execute_query(rem_query)

    logger.info(f"Query completed successfully: {query_type}")

    # Provide helpful guidance when no results found
    response: dict[str, Any] = {
        "query_type": query_type,
        "results": result,
    }

    # Check if results are empty - handle both list and dict result formats
    is_empty = False
    if not result:
        is_empty = True
    elif isinstance(result, list) and len(result) == 0:
        is_empty = True
    elif isinstance(result, dict):
        # RemService returns dict with 'results' key containing actual matches
        inner_results = result.get("results", [])
        count = result.get("count", len(inner_results) if isinstance(inner_results, list) else 0)
        is_empty = count == 0 or (isinstance(inner_results, list) and len(inner_results) == 0)

    if is_empty:
        # Build helpful suggestions based on query type
        suggestions = []

        if query_type in ("LOOKUP", "FUZZY"):
            suggestions.append(
                "LOOKUP/FUZZY searches across ALL tables. If you expected results, "
                "verify the entity name is spelled correctly."
            )

        if query_type == "SEARCH":
            if table == "resources":
                suggestions.append(
                    "No results in 'resources' table. Try: SEARCH <text> IN ontologies - "
                    "clinical procedures, drug info, and diagnostic criteria are stored there."
                )
            elif table == "ontologies":
                suggestions.append(
                    "No results in 'ontologies' table. Try: SEARCH <text> IN resources - "
                    "for user-uploaded documents and general content."
                )
            else:
                suggestions.append(
                    "Try: SEARCH <text> IN ontologies (clinical knowledge, procedures, drugs) "
                    "or SEARCH <text> IN resources (documents, files)."
                )

        # Always suggest both tables if no specific table guidance given
        if not suggestions:
            suggestions.append(
                "No results found. Try: SEARCH <text> IN ontologies (clinical procedures, drugs) "
                "or SEARCH <text> IN resources (documents, files)."
            )

        response["suggestions"] = suggestions
        response["hint"] = "0 results returned. See 'suggestions' for alternative search strategies."

    return response


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
    from ...agentic import create_agent
    from ...agentic.context import get_current_context
    from ...utils.schema_loader import load_agent_schema

    # Get parent context for multi-agent support
    # This enables context propagation from parent agent to child agent
    parent_context = get_current_context()

    # Build child context: inherit from parent if available, otherwise use defaults
    if parent_context is not None:
        # Inherit user_id, tenant_id, session_id, is_eval from parent
        # Allow explicit user_id override if provided
        effective_user_id = user_id or parent_context.user_id
        context = parent_context.child_context(agent_schema_uri=agent_schema)
        if user_id is not None:
            # Override user_id if explicitly provided
            context = AgentContext(
                user_id=user_id,
                tenant_id=parent_context.tenant_id,
                session_id=parent_context.session_id,
                default_model=parent_context.default_model,
                agent_schema_uri=agent_schema,
                is_eval=parent_context.is_eval,
            )
        logger.debug(
            f"ask_rem_agent inheriting context from parent: "
            f"user_id={context.user_id}, session_id={context.session_id}"
        )
    else:
        # No parent context - create fresh context (backwards compatible)
        effective_user_id = AgentContext.get_user_id_or_default(
            user_id, source="ask_rem_agent"
        )
        context = AgentContext(
            user_id=effective_user_id,
            tenant_id=effective_user_id or "default",
            default_model=settings.llm.default_model,
            agent_schema_uri=agent_schema,
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
    resource_type: str | None = None,
) -> dict[str, Any]:
    """
    Ingest file into REM, creating searchable PUBLIC resources and embeddings.

    **IMPORTANT: All ingested data is PUBLIC by default.** This is correct for
    shared knowledge bases (ontologies, procedures, reference data). Private
    user-scoped data requires different handling via the CLI with --make-private.

    This tool provides the complete file ingestion pipeline:
    1. **Read**: File from local/S3/HTTP
    2. **Store**: To internal storage (public namespace)
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
        # Ingest local file (local server only)
        ingest_into_rem(
            file_uri="/Users/me/procedure.pdf",
            category="medical",
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

    # Data is PUBLIC by default (user_id=None)
    # Private user-scoped data requires CLI with --make-private flag

    # Delegate to ContentService for centralized ingestion (errors handled by decorator)
    content_service = ContentService()
    result = await content_service.ingest_file(
        file_uri=file_uri,
        user_id=None,  # PUBLIC - all ingested data is shared/public
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
    • rem://agents - List all available agent schemas
    • rem://agents/{agent_name} - Get specific agent schema

    Documentation:
    • rem://schema/entities - Entity schemas (Resource, Message, User, File, Moment)
    • rem://schema/query-types - REM query type documentation

    System Status:
    • rem://status - System health and statistics

    Args:
        uri: Resource URI (e.g., "rem://agents", "rem://agents/ask_rem")

    Returns:
        Dict with:
        - status: "success" or "error"
        - uri: Original URI
        - data: Resource data (format depends on resource type)

    Examples:
        # List all agents
        read_resource(uri="rem://agents")

        # Get specific agent
        read_resource(uri="rem://agents/ask_rem")

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
    # Session naming
    session_name: str | None = None,
    # Risk assessment fields (used by specialized agents)
    risk_level: str | None = None,
    risk_score: int | None = None,
    risk_reasoning: str | None = None,
    recommended_action: str | None = None,
    # Generic extension - any additional key-value pairs
    extra: dict[str, Any] | None = None,
    # Agent schema (auto-populated from context if not provided)
    agent_schema: str | None = None,
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

        session_name: Short 1-3 phrase name describing the session topic.
            Used by the UI to label conversations in the sidebar.
            Examples: "Prescription Drug Questions", "AWS Setup Help",
            "Python Code Review", "Travel Planning".

        risk_level: Risk level indicator (e.g., "green", "orange", "red").
            Used by mental health agents for C-SSRS style assessment.
        risk_score: Numeric risk score (e.g., 0-6 for C-SSRS).
        risk_reasoning: Brief explanation of risk assessment.
        recommended_action: Suggested next steps based on assessment.

        extra: Dict of arbitrary additional metadata. Use this for any
            domain-specific fields not covered by the standard parameters.
            Example: {"topics_detected": ["anxiety", "sleep"], "session_count": 5}
        agent_schema: Optional agent schema name. If not provided, automatically
            populated from the current agent context (for multi-agent tracing).

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

        # Risk assessment example
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
    # Auto-populate agent_schema from context if not provided
    if agent_schema is None:
        from ...agentic.context import get_current_context
        current_context = get_current_context()
        if current_context and current_context.agent_schema_uri:
            agent_schema = current_context.agent_schema_uri

    logger.debug(
        f"Registering metadata: confidence={confidence}, "
        f"risk_level={risk_level}, refs={len(references or [])}, "
        f"sources={len(sources or [])}, agent_schema={agent_schema}"
    )

    result = {
        "status": "success",
        "_metadata_event": True,  # Marker for streaming layer
        "confidence": confidence,
        "references": references,
        "sources": sources,
        "flags": flags,
        "agent_schema": agent_schema,  # Include agent schema for tracing
    }

    # Add session name if provided
    if session_name is not None:
        result["session_name"] = session_name

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


@mcp_tool_error_handler
async def list_schema(
    include_system: bool = False,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    List all schemas (tables) in the REM database.

    Returns metadata about all available tables including their names,
    row counts, and descriptions. Use this to discover what data is
    available before constructing queries.

    Args:
        include_system: If True, include PostgreSQL system tables (pg_*, information_schema).
                       Default False shows only REM application tables.
        user_id: Optional user identifier (defaults to authenticated user or "default")

    Returns:
        Dict with:
        - status: "success" or "error"
        - tables: List of table metadata dicts with:
            - name: Table name
            - schema: Schema name (usually "public")
            - estimated_rows: Approximate row count
            - description: Table comment if available

    Examples:
        # List all REM schemas
        list_schema()

        # Include system tables
        list_schema(include_system=True)
    """
    rem_service = await get_rem_service()
    user_id = AgentContext.get_user_id_or_default(user_id, source="list_schema")

    # Query information_schema for tables
    schema_filter = ""
    if not include_system:
        schema_filter = """
            AND table_schema = 'public'
            AND table_name NOT LIKE 'pg_%'
            AND table_name NOT LIKE '_pg_%'
        """

    query = f"""
        SELECT
            t.table_schema,
            t.table_name,
            pg_catalog.obj_description(
                (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass,
                'pg_class'
            ) as description,
            (
                SELECT reltuples::bigint
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = t.table_name
                AND n.nspname = t.table_schema
            ) as estimated_rows
        FROM information_schema.tables t
        WHERE t.table_type = 'BASE TABLE'
        {schema_filter}
        ORDER BY t.table_schema, t.table_name
    """

    # Access postgres service directly from cache
    postgres_service = _service_cache.get("postgres")
    if not postgres_service:
        postgres_service = rem_service._postgres

    rows = await postgres_service.fetch(query)

    tables = []
    for row in rows:
        tables.append({
            "name": row["table_name"],
            "schema": row["table_schema"],
            "estimated_rows": int(row["estimated_rows"]) if row["estimated_rows"] else 0,
            "description": row["description"],
        })

    logger.info(f"Listed {len(tables)} schemas for user {user_id}")

    return {
        "tables": tables,
        "count": len(tables),
    }


@mcp_tool_error_handler
async def get_schema(
    table_name: str,
    include_indexes: bool = True,
    include_constraints: bool = True,
    columns: list[str] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Get detailed schema information for a specific table.

    Returns column definitions, data types, constraints, and indexes.
    Use this to understand table structure before writing SQL queries.

    Args:
        table_name: Name of the table to inspect (e.g., "resources", "moments")
        include_indexes: Include index information (default True)
        include_constraints: Include constraint information (default True)
        columns: Optional list of specific columns to return. If None, returns all columns.
        user_id: Optional user identifier (defaults to authenticated user or "default")

    Returns:
        Dict with:
        - status: "success" or "error"
        - table_name: Name of the table
        - columns: List of column definitions with:
            - name: Column name
            - type: PostgreSQL data type
            - nullable: Whether NULL is allowed
            - default: Default value if any
            - description: Column comment if available
        - indexes: List of indexes (if include_indexes=True)
        - constraints: List of constraints (if include_constraints=True)
        - primary_key: Primary key column(s)

    Examples:
        # Get full schema for resources table
        get_schema(table_name="resources")

        # Get only specific columns
        get_schema(
            table_name="resources",
            columns=["id", "name", "created_at"]
        )

        # Get schema without indexes
        get_schema(
            table_name="moments",
            include_indexes=False
        )
    """
    rem_service = await get_rem_service()
    user_id = AgentContext.get_user_id_or_default(user_id, source="get_schema")

    # Access postgres service
    postgres_service = _service_cache.get("postgres")
    if not postgres_service:
        postgres_service = rem_service._postgres

    # Verify table exists
    exists_query = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = $1
        )
    """
    exists = await postgres_service.fetchval(exists_query, table_name)
    if not exists:
        return {
            "status": "error",
            "error": f"Table '{table_name}' not found in public schema",
        }

    # Get columns
    columns_filter = ""
    if columns:
        placeholders = ", ".join(f"${i+2}" for i in range(len(columns)))
        columns_filter = f"AND column_name IN ({placeholders})"

    columns_query = f"""
        SELECT
            c.column_name,
            c.data_type,
            c.udt_name,
            c.is_nullable,
            c.column_default,
            c.character_maximum_length,
            c.numeric_precision,
            pg_catalog.col_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                c.ordinal_position
            ) as description
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
        AND c.table_name = $1
        {columns_filter}
        ORDER BY c.ordinal_position
    """

    params = [table_name]
    if columns:
        params.extend(columns)

    column_rows = await postgres_service.fetch(columns_query, *params)

    column_defs = []
    for row in column_rows:
        # Build a more readable type string
        data_type = row["data_type"]
        if row["character_maximum_length"]:
            data_type = f"{data_type}({row['character_maximum_length']})"
        elif row["udt_name"] in ("int4", "int8", "float4", "float8"):
            # Use common type names
            type_map = {"int4": "integer", "int8": "bigint", "float4": "real", "float8": "double precision"}
            data_type = type_map.get(row["udt_name"], data_type)
        elif row["udt_name"] == "vector":
            data_type = "vector"

        column_defs.append({
            "name": row["column_name"],
            "type": data_type,
            "nullable": row["is_nullable"] == "YES",
            "default": row["column_default"],
            "description": row["description"],
        })

    result = {
        "table_name": table_name,
        "columns": column_defs,
        "column_count": len(column_defs),
    }

    # Get primary key
    pk_query = """
        SELECT a.attname as column_name
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = $1::regclass
        AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
    """
    pk_rows = await postgres_service.fetch(pk_query, table_name)
    result["primary_key"] = [row["column_name"] for row in pk_rows]

    # Get indexes
    if include_indexes:
        indexes_query = """
            SELECT
                i.relname as index_name,
                am.amname as index_type,
                ix.indisunique as is_unique,
                ix.indisprimary as is_primary,
                array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) as columns
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_am am ON am.oid = i.relam
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE t.relname = $1
            GROUP BY i.relname, am.amname, ix.indisunique, ix.indisprimary
            ORDER BY i.relname
        """
        index_rows = await postgres_service.fetch(indexes_query, table_name)
        result["indexes"] = [
            {
                "name": row["index_name"],
                "type": row["index_type"],
                "unique": row["is_unique"],
                "primary": row["is_primary"],
                "columns": row["columns"],
            }
            for row in index_rows
        ]

    # Get constraints
    if include_constraints:
        constraints_query = """
            SELECT
                con.conname as constraint_name,
                con.contype as constraint_type,
                array_agg(a.attname ORDER BY array_position(con.conkey, a.attnum)) as columns,
                pg_get_constraintdef(con.oid) as definition
            FROM pg_constraint con
            JOIN pg_class t ON t.oid = con.conrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(con.conkey)
            WHERE t.relname = $1
            GROUP BY con.conname, con.contype, con.oid
            ORDER BY con.contype, con.conname
        """
        constraint_rows = await postgres_service.fetch(constraints_query, table_name)

        # Map constraint types to readable names
        type_map = {
            "p": "PRIMARY KEY",
            "u": "UNIQUE",
            "f": "FOREIGN KEY",
            "c": "CHECK",
            "x": "EXCLUSION",
        }

        result["constraints"] = []
        for row in constraint_rows:
            # contype is returned as bytes (char type), decode it
            con_type = row["constraint_type"]
            if isinstance(con_type, bytes):
                con_type = con_type.decode("utf-8")
            result["constraints"].append({
                "name": row["constraint_name"],
                "type": type_map.get(con_type, con_type),
                "columns": row["columns"],
                "definition": row["definition"],
            })

    logger.info(f"Retrieved schema for table '{table_name}' with {len(column_defs)} columns")

    return result


@mcp_tool_error_handler
async def save_agent(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    tools: list[str] | None = None,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Save an agent schema to REM, making it available for use.

    This tool creates or updates an agent definition in the user's schema space.
    The agent becomes immediately available for conversations.

    **Default Tools**: All agents automatically get `search_rem` and `register_metadata`
    tools unless explicitly overridden.

    Args:
        name: Agent name in kebab-case (e.g., "code-reviewer", "sales-assistant").
            Must be unique within the user's schema space.
        description: The agent's system prompt. This is the full instruction set
            that defines the agent's behavior, personality, and capabilities.
            Use markdown formatting for structure.
        properties: Output schema properties as a dict. Each property should have:
            - type: "string", "number", "boolean", "array", "object"
            - description: What this field captures
            Example: {"answer": {"type": "string", "description": "Response to user"}}
            If not provided, defaults to a simple {"answer": {"type": "string"}} schema.
        required: List of required property names. Defaults to ["answer"] if not provided.
        tools: List of tool names the agent can use. Defaults to ["search_rem", "register_metadata"].
        tags: Optional tags for categorizing the agent.
        version: Semantic version string (default: "1.0.0").
        user_id: User identifier for scoping. Uses authenticated user if not provided.

    Returns:
        Dict with:
        - status: "success" or "error"
        - agent_name: Name of the saved agent
        - version: Version saved
        - message: Human-readable status

    Examples:
        # Create a simple agent
        save_agent(
            name="greeting-bot",
            description="You are a friendly greeter. Say hello warmly.",
            properties={"answer": {"type": "string", "description": "Greeting message"}},
            required=["answer"]
        )

        # Create agent with structured output
        save_agent(
            name="sentiment-analyzer",
            description="Analyze sentiment of text provided by the user.",
            properties={
                "answer": {"type": "string", "description": "Analysis explanation"},
                "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            required=["answer", "sentiment"],
            tags=["analysis", "nlp"]
        )
    """
    from ...agentic.agents.agent_manager import save_agent as _save_agent

    # Get user_id from context if not provided
    user_id = AgentContext.get_user_id_or_default(user_id, source="save_agent")

    # Delegate to agent_manager
    result = await _save_agent(
        name=name,
        description=description,
        user_id=user_id,
        properties=properties,
        required=required,
        tools=tools,
        tags=tags,
        version=version,
    )

    # Add helpful message for Slack users
    if result.get("status") == "success":
        result["message"] = f"Agent '{name}' saved. Use `/custom-agent {name}` to chat with it."

    return result


# =============================================================================
# Multi-Agent Tools
# =============================================================================


@mcp_tool_error_handler
async def ask_agent(
    agent_name: str,
    input_text: str,
    input_data: dict[str, Any] | None = None,
    user_id: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """
    Invoke another agent by name and return its response.

    This tool enables multi-agent orchestration by allowing one agent to call
    another. The child agent inherits the parent's context (user_id, session_id,
    tenant_id, is_eval) for proper scoping and continuity.

    Use Cases:
    - Orchestrator agents that delegate to specialized sub-agents
    - Workflow agents that chain multiple processing steps
    - Ensemble agents that aggregate responses from multiple specialists

    Args:
        agent_name: Name of the agent to invoke. Can be:
            - A user-created agent (saved via save_agent)
            - A system agent (e.g., "ask_rem", "knowledge-query")
        input_text: The user message/query to send to the agent
        input_data: Optional structured input data for the agent
        user_id: Optional user override (defaults to parent's user_id)
        timeout_seconds: Maximum execution time (default: 300s)

    Returns:
        Dict with:
        - status: "success" or "error"
        - output: Agent's structured output (if using output schema)
        - text_response: Agent's text response
        - agent_schema: Name of the invoked agent
        - metadata: Any metadata registered by the agent (confidence, etc.)

    Examples:
        # Simple delegation
        ask_agent(
            agent_name="sentiment-analyzer",
            input_text="I love this product! Best purchase ever."
        )
        # Returns: {"status": "success", "output": {"sentiment": "positive"}, ...}

        # Orchestrator pattern
        ask_agent(
            agent_name="knowledge-query",
            input_text="What are the latest Q3 results?"
        )

        # Chain with structured input
        ask_agent(
            agent_name="summarizer",
            input_text="Summarize this document",
            input_data={"document_id": "doc-123", "max_length": 500}
        )
    """
    import asyncio
    from ...agentic import create_agent
    from ...agentic.context import get_current_context, agent_context_scope, get_event_sink, push_event
    from ...agentic.agents.agent_manager import get_agent
    from ...utils.schema_loader import load_agent_schema

    # Get parent context for inheritance
    parent_context = get_current_context()

    # Determine effective user_id
    if parent_context is not None:
        effective_user_id = user_id or parent_context.user_id
    else:
        effective_user_id = AgentContext.get_user_id_or_default(
            user_id, source="ask_agent"
        )

    # Build child context
    if parent_context is not None:
        child_context = parent_context.child_context(agent_schema_uri=agent_name)
        if user_id is not None:
            # Explicit user_id override
            child_context = AgentContext(
                user_id=user_id,
                tenant_id=parent_context.tenant_id,
                session_id=parent_context.session_id,
                default_model=parent_context.default_model,
                agent_schema_uri=agent_name,
                is_eval=parent_context.is_eval,
            )
        logger.debug(
            f"ask_agent '{agent_name}' inheriting context: "
            f"user_id={child_context.user_id}, session_id={child_context.session_id}"
        )
    else:
        child_context = AgentContext(
            user_id=effective_user_id,
            tenant_id=effective_user_id or "default",
            default_model=settings.llm.default_model,
            agent_schema_uri=agent_name,
        )

    # Try to load agent schema from:
    # 1. Database (user-created or system agents)
    # 2. File system (packaged agents)
    schema = None

    # Try database first
    if effective_user_id:
        schema = await get_agent(agent_name, user_id=effective_user_id)
        if schema:
            logger.debug(f"Loaded agent '{agent_name}' from database")

    # Fall back to file system
    if schema is None:
        try:
            schema = load_agent_schema(agent_name)
            logger.debug(f"Loaded agent '{agent_name}' from file system")
        except FileNotFoundError:
            pass

    if schema is None:
        return {
            "status": "error",
            "error": f"Agent not found: {agent_name}",
            "hint": "Use list_agents to see available agents, or save_agent to create one",
        }

    # Create agent runtime
    agent_runtime = await create_agent(
        context=child_context,
        agent_schema_override=schema,
    )

    # Build prompt with optional input_data
    prompt = input_text
    if input_data:
        prompt = f"{input_text}\n\nInput data: {json.dumps(input_data)}"

    # Load session history for the sub-agent (CRITICAL for multi-turn conversations)
    # Sub-agents need to see the full conversation context, not just the summary
    pydantic_message_history = None
    if child_context.session_id and settings.postgres.enabled:
        try:
            from ...services.session import SessionMessageStore, session_to_pydantic_messages
            from ...agentic.schema import get_system_prompt

            store = SessionMessageStore(user_id=child_context.user_id or "default")
            raw_session_history = await store.load_session_messages(
                session_id=child_context.session_id,
                user_id=child_context.user_id,
                compress_on_load=False,  # Need full data for reconstruction
            )
            if raw_session_history:
                # Extract agent's system prompt from schema
                agent_system_prompt = get_system_prompt(schema) if schema else None
                pydantic_message_history = session_to_pydantic_messages(
                    raw_session_history,
                    system_prompt=agent_system_prompt,
                )
                logger.debug(
                    f"ask_agent '{agent_name}': loaded {len(raw_session_history)} session messages "
                    f"-> {len(pydantic_message_history)} pydantic-ai messages"
                )

                # Audit session history if enabled
                from ...services.session import audit_session_history
                audit_session_history(
                    session_id=child_context.session_id,
                    agent_name=agent_name,
                    prompt=prompt,
                    raw_session_history=raw_session_history,
                    pydantic_messages_count=len(pydantic_message_history),
                )
        except Exception as e:
            logger.warning(f"ask_agent '{agent_name}': failed to load session history: {e}")
            # Fall back to running without history

    # Run agent with timeout and context propagation
    logger.info(f"Invoking agent '{agent_name}' with prompt: {prompt[:100]}...")

    # Check if we have an event sink for streaming
    push_event = get_event_sink()
    use_streaming = push_event is not None

    streamed_content = ""  # Track if content was streamed

    try:
        # Set child context for nested tool calls
        with agent_context_scope(child_context):
            if use_streaming:
                # STREAMING MODE: Use iter() and proxy events to parent
                logger.debug(f"ask_agent '{agent_name}': using streaming mode with event proxying")

                async def run_with_streaming():
                    from pydantic_ai.messages import (
                        PartStartEvent, PartDeltaEvent, PartEndEvent,
                        FunctionToolResultEvent, FunctionToolCallEvent,
                    )
                    from pydantic_ai.agent import Agent

                    accumulated_content = []
                    child_tool_calls = []

                    # iter() returns an async context manager, not an awaitable
                    iter_kwargs = {"message_history": pydantic_message_history} if pydantic_message_history else {}
                    async with agent_runtime.iter(prompt, **iter_kwargs) as agent_run:
                        async for node in agent_run:
                            if Agent.is_model_request_node(node):
                                async with node.stream(agent_run.ctx) as request_stream:
                                    async for event in request_stream:
                                        # Proxy part starts (text content only - tool calls handled in is_call_tools_node)
                                        if isinstance(event, PartStartEvent):
                                            from pydantic_ai.messages import ToolCallPart, TextPart
                                            if isinstance(event.part, ToolCallPart):
                                                # Track tool call for later (args are incomplete at PartStartEvent)
                                                # Full args come via FunctionToolCallEvent in is_call_tools_node
                                                child_tool_calls.append({
                                                    "tool_name": event.part.tool_name,
                                                    "index": event.index,
                                                })
                                            elif isinstance(event.part, TextPart):
                                                # TextPart may have initial content
                                                if event.part.content:
                                                    accumulated_content.append(event.part.content)
                                                    await push_event.put({
                                                        "type": "child_content",
                                                        "agent_name": agent_name,
                                                        "content": event.part.content,
                                                    })
                                        # Proxy text content deltas to parent for real-time streaming
                                        elif isinstance(event, PartDeltaEvent):
                                            if hasattr(event, 'delta') and hasattr(event.delta, 'content_delta'):
                                                content = event.delta.content_delta
                                                if content:
                                                    accumulated_content.append(content)
                                                    # Push content chunk to parent for streaming
                                                    await push_event.put({
                                                        "type": "child_content",
                                                        "agent_name": agent_name,
                                                        "content": content,
                                                    })

                            elif Agent.is_call_tools_node(node):
                                async with node.stream(agent_run.ctx) as tools_stream:
                                    async for tool_event in tools_stream:
                                        # FunctionToolCallEvent fires when tool call is parsed
                                        # with complete arguments (before execution)
                                        if isinstance(tool_event, FunctionToolCallEvent):
                                            # Get full arguments from completed tool call
                                            tool_args = None
                                            if hasattr(tool_event, 'part') and hasattr(tool_event.part, 'args'):
                                                raw_args = tool_event.part.args
                                                if isinstance(raw_args, str):
                                                    try:
                                                        tool_args = json.loads(raw_args)
                                                    except json.JSONDecodeError:
                                                        tool_args = {"raw": raw_args}
                                                elif isinstance(raw_args, dict):
                                                    tool_args = raw_args
                                            # Push tool start with full arguments
                                            await push_event.put({
                                                "type": "child_tool_start",
                                                "agent_name": agent_name,
                                                "tool_name": tool_event.part.tool_name if hasattr(tool_event, 'part') else "unknown",
                                                "arguments": tool_args,
                                            })
                                        elif isinstance(tool_event, FunctionToolResultEvent):
                                            result_content = tool_event.result.content if hasattr(tool_event.result, 'content') else tool_event.result
                                            # Push tool result to parent
                                            await push_event.put({
                                                "type": "child_tool_result",
                                                "agent_name": agent_name,
                                                "result": result_content,
                                            })

                        # Get final result (inside context manager)
                        return agent_run.result, "".join(accumulated_content), child_tool_calls

                result, streamed_content, tool_calls = await asyncio.wait_for(
                    run_with_streaming(),
                    timeout=timeout_seconds
                )
            else:
                # NON-STREAMING MODE: Use run() for backwards compatibility
                if pydantic_message_history:
                    result = await asyncio.wait_for(
                        agent_runtime.run(prompt, message_history=pydantic_message_history),
                        timeout=timeout_seconds
                    )
                else:
                    result = await asyncio.wait_for(
                        agent_runtime.run(prompt),
                        timeout=timeout_seconds
                    )
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "error": f"Agent '{agent_name}' timed out after {timeout_seconds}s",
            "agent_schema": agent_name,
        }

    # Serialize output
    from rem.agentic.serialization import serialize_agent_result
    output = serialize_agent_result(result.output)

    logger.info(f"Agent '{agent_name}' completed successfully")

    response = {
        "status": "success",
        "output": output,
        "agent_schema": agent_name,
        "input_text": input_text,
    }

    # Only include text_response if content was NOT streamed
    # When streaming, child_content events already delivered the content
    if not use_streaming or not streamed_content:
        response["text_response"] = str(result.output)

    return response


# =============================================================================
# Test/Debug Tools (for development only)
# =============================================================================

@mcp_tool_error_handler
async def test_error_handling(
    error_type: Literal["exception", "error_response", "timeout", "success"] = "success",
    delay_seconds: float = 0,
    error_message: str = "Test error occurred",
) -> dict[str, Any]:
    """
    Test tool for simulating different error scenarios.

    **FOR DEVELOPMENT/TESTING ONLY** - This tool helps verify that error
    handling works correctly through the streaming layer.

    Args:
        error_type: Type of error to simulate:
            - "success": Returns successful response (default)
            - "exception": Raises an exception (tests @mcp_tool_error_handler)
            - "error_response": Returns {"status": "error", ...} dict
            - "timeout": Delays for 60 seconds (simulates timeout)
        delay_seconds: Optional delay before responding (0-10 seconds)
        error_message: Custom error message for error scenarios

    Returns:
        Dict with test results or error information

    Examples:
        # Test successful response
        test_error_handling(error_type="success")

        # Test exception handling
        test_error_handling(error_type="exception", error_message="Database connection failed")

        # Test error response format
        test_error_handling(error_type="error_response", error_message="Resource not found")

        # Test with delay
        test_error_handling(error_type="success", delay_seconds=2)
    """
    import asyncio

    logger.info(f"test_error_handling called: type={error_type}, delay={delay_seconds}")

    # Apply delay (capped at 10 seconds for safety)
    if delay_seconds > 0:
        await asyncio.sleep(min(delay_seconds, 10))

    if error_type == "exception":
        # This tests the @mcp_tool_error_handler decorator
        raise RuntimeError(f"TEST EXCEPTION: {error_message}")

    elif error_type == "error_response":
        # This tests how the streaming layer handles error status responses
        return {
            "status": "error",
            "error": error_message,
            "error_code": "TEST_ERROR",
            "recoverable": True,
        }

    elif error_type == "timeout":
        # Simulate a very long operation (for testing client-side timeouts)
        await asyncio.sleep(60)
        return {"status": "success", "message": "Timeout test completed (should not reach here)"}

    else:  # success
        return {
            "status": "success",
            "message": "Test completed successfully",
            "test_data": {
                "error_type": error_type,
                "delay_applied": delay_seconds,
                "timestamp": str(asyncio.get_event_loop().time()),
            },
        }
