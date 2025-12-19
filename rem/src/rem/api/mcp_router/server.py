"""
MCP server creation and configuration for REM.

Design Pattern
1. Create FastMCP server with tools and resources
2. Register tools using @mcp.tool() decorator
3. Register resources using resource registration functions
4. Mount on FastAPI at /api/v1/mcp
5. Support both HTTP and SSE transports

Key Concepts:
- Tools: Functions LLM can call (search, query, parse, etc.)
- Resources: Read-only data sources (entity lookups, schema docs, etc.)
- Instructions: System-level guidance for LLM on how to use MCP server

FastMCP Features:
- Stateless HTTP mode (stateless_http=True) prevents stale session errors
- Path="/" creates routes at root, then mount at custom path
- Built-in auth that can be disabled for testing
"""

import importlib.metadata
from functools import wraps

from fastmcp import FastMCP
from loguru import logger

from ...settings import settings
from .prompts import register_prompts
from .resources import (
    register_agent_resources,
    register_file_resources,
    register_schema_resources,
    register_status_resources,
)
from .tools import (
    ask_agent,
    ask_rem_agent,
    get_schema,
    ingest_into_rem,
    list_schema,
    read_resource,
    register_metadata,
    save_agent,
    search_rem,
    test_error_handling,
)

# Get package version
try:
    __version__ = importlib.metadata.version("remdb")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"


def create_mcp_server(is_local: bool = False) -> FastMCP:
    """
    Create and configure the REM MCP server with all tools and resources.

    Args:
        is_local: True if running as local/stdio server (enables file ingestion from local paths)

    Returns:
        Configured FastMCP server instance

    Usage Modes:
        # Stdio mode (for local dev / Claude Desktop)
        mcp = create_mcp_server(is_local=True)
        mcp.run(transport="stdio")

        # HTTP mode (for production / API)
        mcp = create_mcp_server(is_local=False)
        mcp_app = mcp.http_app(path="/", transport="http", stateless_http=True)
        # Then mount: app.mount("/api/v1/mcp", mcp_app)

    Design Pattern
    - Instructions provide LLM guidance on workflow
    - Tools implement specific operations
    - Resources provide read-only access to data
    - All modular and testable
    """
    mcp = FastMCP(
        name=f"REM MCP Server ({settings.team}/{settings.environment})",
        version=__version__,
        instructions=(
            "REM (Resource-Entity-Moment) MCP Server - Unified memory infrastructure for agentic systems.\n\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "REM QUERY WORKFLOW - Schema-Agnostic Natural Language Queries\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "\n"
            "**IMPORTANT:** REM uses natural language labels, NOT UUIDs. You query with:\n"
            "- LOOKUP \"Sarah Chen\" (what user knows)\n"
            "- NOT LOOKUP \"sarah-chen-uuid-1234\" (internal ID)\n"
            "\n"
            "REM Query Types:\n"
            "\n"
            "1. LOOKUP - O(1) entity resolution across ALL tables\n"
            "   Example: LOOKUP \"Sarah Chen\"\n"
            "   Returns: All entities named \"Sarah Chen\" (resources, moments, users)\n"
            "\n"
            "2. FUZZY - Indexed fuzzy text matching\n"
            "   Example: FUZZY \"sara\" threshold=0.7\n"
            "   Returns: \"Sarah Chen\", \"Sara Martinez\", etc.\n"
            "\n"
            "3. SEARCH - Semantic vector search (table-specific)\n"
            "   Example: SEARCH \"database migration\" table=resources\n"
            "   Returns: Semantically similar resources\n"
            "\n"
            "4. SQL - Direct table queries with WHERE clauses\n"
            "   Example: SQL table=moments WHERE moment_type='meeting'\n"
            "   Returns: All meeting moments\n"
            "\n"
            "5. TRAVERSE - Multi-hop graph traversal\n"
            "   Example: TRAVERSE manages WITH LOOKUP \"Sally\" DEPTH 2\n"
            "   Returns: Sally + her team hierarchy\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "ITERATED RETRIEVAL PATTERN - Multi-Turn Exploration\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "\n"
            "REM is designed for multi-turn exploration, not single-shot queries:\n"
            "\n"
            "Turn 1: Find entry point\n"
            "  LOOKUP \"Sarah Chen\"\n"
            "  → Found person entity with 3 graph edges\n"
            "\n"
            "Turn 2: Analyze neighborhood (PLAN mode - depth 0)\n"
            "  ask_rem(\"What are Sarah Chen's connections?\", plan_mode=True)\n"
            "  → Agent uses TRAVERSE with max_depth=0\n"
            "  → Edge summary: manages(2), authored_by(15), mentors(3)\n"
            "\n"
            "Turn 3: Selective traversal\n"
            "  ask_rem(\"Show Sarah Chen's team hierarchy\")\n"
            "  → Agent uses TRAVERSE with rel_type=\"manages\", max_depth=2\n"
            "  → Returns: Sarah + team hierarchy (depth 2)\n"
            "\n"
            "Turn 4: Follow reference chain\n"
            "  TRAVERSE references,builds-on WITH LOOKUP \"api-design-v2\" DEPTH 1\n"
            "  → Returns: Design lineage\n"
            "\n"
            "**Key Concepts:**\n"
            "- Depth 0 = PLAN mode (analyze edges without traversal)\n"
            "- Depth 1+ = Full traversal with cycle detection\n"
            "- Plan memo = Agent scratchpad for multi-turn tracking\n"
            "- Edge filters = Selective relationship types\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "AVAILABLE TOOLS\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "\n"
            "• search_rem - Execute REM queries (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)\n"
            "• ask_rem_agent - Natural language to REM query conversion\n"
            "  - plan_mode=True: Hints agent to use TRAVERSE with depth=0 for edge analysis\n"
            "• ingest_into_rem - Ingest files from local paths (local server only), s3://, or https://\n"
            "• list_schema - List all database schemas (tables) with row counts\n"
            "• get_schema - Get detailed schema for a specific table (columns, types, indexes)\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "AVAILABLE RESOURCES (Read-Only)\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "\n"
            "Schema Information:\n"
            "• rem://schema/entities - Entity schemas (Resource, Message, User, File, Moment)\n"
            "• rem://schema/query-types - REM query type documentation\n"
            "\n"
            "Agent Schemas:\n"
            "• rem://agents - List available agent schemas with descriptions and usage\n"
            "\n"
            "File Operations:\n"
            "• rem://files/presigned-url - Generate presigned S3 URLs for file download\n"
            "\n"
            "System Status:\n"
            "• rem://status - System health and statistics\n"
            "\n"
            "**Quick Start:**\n"
            "1. User: \"Who is Sarah?\"\n"
            "   → Call: search_rem(query_type=\"lookup\", entity_key=\"Sarah\", user_id=\"...\")\n"
            "\n"
            "2. User: \"Find documents about database migration\"\n"
            "   → Call: search_rem(query_type=\"search\", query_text=\"database migration\", table=\"resources\", user_id=\"...\")\n"
            "\n"
            "3. User: \"Who reports to Sally?\"\n"
            "   → Call: search_rem(query_type=\"traverse\", initial_query=\"Sally\", edge_types=[\"reports-to\"], depth=2, user_id=\"...\")\n"
            "\n"
            "4. User: \"Show me Sarah's org chart\" (Multi-turn example)\n"
            "   → Turn 1: search_rem(query_type=\"lookup\", entity_key=\"Sarah\", user_id=\"...\")\n"
            "   → Turn 2: search_rem(query_type=\"traverse\", initial_query=\"Sarah\", depth=0, user_id=\"...\")  # PLAN mode\n"
            "   → Turn 3: search_rem(query_type=\"traverse\", initial_query=\"Sarah\", edge_types=[\"manages\", \"reports-to\"], depth=2, user_id=\"...\")\n"
            "\n"
            "5. User: \"What did we discuss last week about the TiDB migration?\"\n"
            "   → Call: ask_rem_agent(query=\"What did we discuss last week about the TiDB migration?\", user_id=\"...\")\n"
            "\n"
            "6. User: \"Ingest this PDF file\"\n"
            "   → Call: ingest_into_rem(file_uri=\"s3://bucket/file.pdf\", user_id=\"...\")\n"
        ),
    )

    # Register core REM tools
    mcp.tool()(search_rem)
    mcp.tool()(ask_rem_agent)
    mcp.tool()(read_resource)
    mcp.tool()(register_metadata)
    mcp.tool()(list_schema)
    mcp.tool()(get_schema)
    mcp.tool()(save_agent)

    # Register multi-agent tools
    mcp.tool()(ask_agent)

    # Register test tool only in development environment (not staging/production)
    if settings.environment not in ("staging", "production"):
        mcp.tool()(test_error_handling)
        logger.debug("Registered test_error_handling tool (dev environment only)")

    # File ingestion tool (with local path support for local servers)
    # Wrap to inject is_local parameter
    @wraps(ingest_into_rem)
    async def ingest_into_rem_wrapper(
        file_uri: str,
        user_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ):
        return await ingest_into_rem(
            file_uri=file_uri,
            user_id=user_id,
            category=category,
            tags=tags,
            is_local_server=is_local,
        )

    mcp.tool()(ingest_into_rem_wrapper)

    # Register prompts
    register_prompts(mcp)

    # Register schema resources
    register_schema_resources(mcp)
    register_agent_resources(mcp)
    register_file_resources(mcp)
    register_status_resources(mcp)

    return mcp
