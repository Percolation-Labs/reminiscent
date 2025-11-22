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


async def search_rem(
    query_type: Literal["lookup", "fuzzy", "search", "sql", "traverse"],
    tenant_id: str,
    # LOOKUP parameters
    entity_key: str | None = None,
    user_id: str | None = None,
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
    - Full PostgreSQL query power
    - Example: SQL "SELECT * FROM users WHERE role = 'engineer'"

    **TRAVERSE** - Graph traversal following relationships:
    - Explores entity neighborhood via graph edges
    - Supports depth control and edge type filtering
    - Example: TRAVERSE "Sarah Chen" edge_types=["manages", "reports_to"] depth=2

    Args:
        query_type: Type of query (lookup, fuzzy, search, sql, traverse)
        tenant_id: Tenant identifier for data isolation
        entity_key: Entity key for LOOKUP (e.g., "Sarah Chen")
        user_id: Optional user filter for LOOKUP
        query_text: Search text for FUZZY or SEARCH
        threshold: Similarity threshold for FUZZY (0.0-1.0)
        table: Target table for SEARCH (resources, moments, users, etc.)
        limit: Max results for SEARCH
        sql_query: SQL query string for SQL type
        initial_query: Starting entity for TRAVERSE
        edge_types: Edge types to follow for TRAVERSE (e.g., ["manages", "reports_to"])
        depth: Traversal depth for TRAVERSE (0=plan only, 1-5=actual traversal)

    Returns:
        Dict with query results, metadata, and execution info

    Examples:
        # Lookup entity
        search_rem(
            query_type="lookup",
            entity_key="Sarah Chen",
            tenant_id="acme-corp"
        )

        # Semantic search
        search_rem(
            query_type="search",
            query_text="database migration",
            table="resources",
            tenant_id="acme-corp",
            limit=10
        )

        # Graph traversal
        search_rem(
            query_type="traverse",
            initial_query="Sarah Chen",
            edge_types=["manages", "reports_to"],
            depth=2,
            tenant_id="acme-corp"
        )
    """
    if not _rem_service:
        return {
            "status": "error",
            "error": "RemService not initialized. Check server startup.",
        }

    try:
        # Build RemQuery based on query_type
        if query_type == "lookup":
            if not entity_key:
                return {"status": "error", "error": "entity_key required for LOOKUP"}

            query = RemQuery(
                query_type=QueryType.LOOKUP,
                parameters=LookupParameters(
                    entity_key=entity_key,
                    tenant_id=tenant_id,
                    user_id=user_id,
                ),
            )

        elif query_type == "fuzzy":
            if not query_text:
                return {"status": "error", "error": "query_text required for FUZZY"}

            query = RemQuery(
                query_type=QueryType.FUZZY,
                parameters=FuzzyParameters(
                    query_text=query_text,
                    tenant_id=tenant_id,
                    threshold=threshold,
                    user_id=user_id,
                ),
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
                    table=table,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    limit=limit,
                ),
            )

        elif query_type == "sql":
            if not sql_query:
                return {"status": "error", "error": "sql_query required for SQL"}

            query = RemQuery(
                query_type=QueryType.SQL,
                parameters=SQLParameters(
                    sql_query=sql_query,
                    tenant_id=tenant_id,
                ),
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
                    depth=depth,
                    tenant_id=tenant_id,
                    user_id=user_id,
                ),
            )

        else:
            return {"status": "error", "error": f"Unknown query_type: {query_type}"}

        # Execute query
        logger.info(f"Executing REM query: {query_type} for tenant {tenant_id}")
        result = await _rem_service.execute_query(query)

        logger.info(f"Query completed successfully: {query_type}")
        return {
            "status": "success",
            "query_type": query_type,
            "results": result,
        }

    except Exception as e:
        logger.error(f"REM query failed: {e}", exc_info=True)
        return {
            "status": "error",
            "query_type": query_type,
            "error": str(e),
        }


async def ask_rem_agent(
    query: str,
    tenant_id: str,
    user_id: str | None = None,
    agent_schema: str = "ask_rem",
    agent_version: str | None = None,
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
        tenant_id: Tenant identifier for data isolation
        user_id: Optional user identifier
        agent_schema: Agent schema name (default: "ask_rem")
        agent_version: Optional agent version (default: latest)

    Returns:
        Dict with:
        - status: "success" or "error"
        - response: Agent's natural language response
        - query_output: Structured query results (if available)
        - queries_executed: List of REM queries executed
        - metadata: Agent execution metadata

    Examples:
        # Simple question
        ask_rem_agent(
            query="Who is Sarah Chen?",
            tenant_id="acme-corp"
        )

        # Complex multi-step question
        ask_rem_agent(
            query="What are the key findings from last week's sprint retrospective?",
            tenant_id="acme-corp",
            user_id="john-doe"
        )

        # Graph exploration
        ask_rem_agent(
            query="Show me Sarah's reporting chain and their recent projects",
            tenant_id="acme-corp"
        )
    """
    try:
        from ...agentic import AgentContext, create_agent
        from ...services.schema_repository import SchemaRepository

        # Create agent context
        context = AgentContext(
            user_id=user_id,
            tenant_id=tenant_id,
            default_model=settings.llm.default_model,
        )

        # Load agent schema
        schema_repo = SchemaRepository()
        schema = await schema_repo.get_schema(agent_schema, agent_version)

        if not schema:
            return {
                "status": "error",
                "error": f"Agent schema not found: {agent_schema}",
            }

        # Create agent
        agent = await create_agent(
            context=context,
            agent_schema_override=schema,
        )

        # Run agent
        logger.info(f"Running ask_rem agent for query: {query[:100]}...")
        result = await agent.run(query)

        # Extract output
        from rem.agentic.serialization import serialize_agent_result
        query_output = serialize_agent_result(result.output)

        logger.info("Agent execution completed successfully")

        return {
            "status": "success",
            "response": str(result.output),
            "query_output": query_output,
            "natural_query": query,
        }

    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "natural_query": query,
        }


async def ingest_into_rem(
    file_uri: str,
    tenant_id: str,
    user_id: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    is_local_server: bool = False,
) -> dict[str, Any]:
    """
    Ingest file into REM, creating searchable resources and embeddings.

    This tool provides the complete file ingestion pipeline:
    1. **Read**: File from local/S3/HTTP
    2. **Store**: To tenant-scoped internal storage
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
        tenant_id: Tenant identifier for data isolation
        user_id: Optional user ownership
        category: Optional category (document, code, audio, etc.)
        tags: Optional tags for file
        is_local_server: True if running as local/stdio MCP server

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
            file_uri="/Users/me/contract.pdf",
            tenant_id="acme-corp",
            category="legal",
            is_local_server=True
        )

        # Ingest from S3
        ingest_into_rem(
            file_uri="s3://bucket/docs/report.pdf",
            tenant_id="acme-corp"
        )

        # Ingest from HTTP
        ingest_into_rem(
            file_uri="https://example.com/whitepaper.pdf",
            tenant_id="acme-corp",
            tags=["research", "whitepaper"]
        )
    """
    from ...services.content import ContentService

    try:
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

        return {
            "status": "success",
            **result,
        }

    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Remote servers cannot access local files. Use S3 or HTTP URLs.",
        }

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": f"File not found: {file_uri}",
        }

    except Exception as e:
        logger.exception(f"Ingestion failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": f"Failed to ingest file: {file_uri}",
        }


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
    try:
        logger.info(f"📖 Reading resource: {uri}")

        # Import here to avoid circular dependency
        from .resources import load_resource

        # Load resource using the existing resource handler
        result = await load_resource(uri)

        logger.info(f"✓ Resource loaded successfully: {uri}")

        # If result is already a dict, return it
        if isinstance(result, dict):
            return {
                "status": "success",
                "uri": uri,
                "data": result,
            }

        # If result is a string (JSON), parse it
        import json

        try:
            data = json.loads(result)
            return {
                "status": "success",
                "uri": uri,
                "data": data,
            }
        except json.JSONDecodeError:
            # Return as plain text if not JSON
            return {
                "status": "success",
                "uri": uri,
                "data": {"content": result},
            }

    except Exception as e:
        logger.error(f"Failed to read resource {uri}: {e}")
        return {
            "status": "error",
            "uri": uri,
            "error": str(e),
        }
