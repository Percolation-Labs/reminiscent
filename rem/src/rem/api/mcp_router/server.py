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

from fastmcp import FastMCP

from ...settings import settings


def create_mcp_server() -> FastMCP:
    """
    Create and configure the REM MCP server with all tools and resources.

    Returns:
        Configured FastMCP server instance

    Usage Modes:
        # Stdio mode (for local dev / Claude Desktop)
        mcp = create_mcp_server()
        mcp.run(transport="stdio")

        # HTTP mode (for production / API)
        mcp = create_mcp_server()
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
        version="0.1.0",
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
            "  TRAVERSE WITH LOOKUP \"Sarah Chen\" DEPTH 0\n"
            "  → Edge summary: manages(2), authored_by(15), mentors(3)\n"
            "\n"
            "Turn 3: Selective traversal\n"
            "  TRAVERSE manages,mentors WITH LOOKUP \"Sarah Chen\" DEPTH 2\n"
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
            "Core REM Operations:\n"
            "• rem_query - Execute REM queries (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)\n"
            "• ask_rem - Natural language to REM query conversion\n"
            "\n"
            "Resource Management:\n"
            "• create_resource - Create new resource with content\n"
            "• create_moment - Create temporal narrative\n"
            "• update_graph_edges - Add/update entity graph edges\n"
            "\n"
            "File Operations:\n"
            "• upload_file - Upload file to S3 (tenant-scoped)\n"
            "• download_file - Download file from S3\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "AVAILABLE RESOURCES (Read-Only)\n"
            "═══════════════════════════════════════════════════════════════════════════\n"
            "\n"
            "Schema Information:\n"
            "• rem://schema/entities - Entity schemas (Resource, Message, User, File, Moment)\n"
            "• rem://schema/query-types - REM query type documentation\n"
            "\n"
            "System Status:\n"
            "• rem://status - System health and statistics\n"
            "\n"
            "**Quick Start:**\n"
            "1. User: \"Who is Sarah?\"\n"
            "   → Call: rem_query(query_type=\"lookup\", key=\"Sarah\")\n"
            "\n"
            "2. User: \"Find documents about database migration\"\n"
            "   → Call: rem_query(query_type=\"search\", query_text=\"database migration\", table=\"resources\")\n"
            "\n"
            "3. User: \"Who reports to Sally?\"\n"
            "   → Call: rem_query(query_type=\"traverse\", initial_query=\"Sally\", edge_types=[\"reports-to\"], depth=2)\n"
            "\n"
            "4. User: \"Show me Sarah's org chart\" (Multi-turn example)\n"
            "   → Turn 1: rem_query(query_type=\"lookup\", key=\"Sarah\")\n"
            "   → Turn 2: rem_query(query_type=\"traverse\", initial_query=\"Sarah\", depth=0)  # PLAN mode\n"
            "   → Turn 3: rem_query(query_type=\"traverse\", initial_query=\"Sarah\", edge_types=[\"manages\", \"reports-to\"], depth=2)\n"
        ),
    )

    # TODO: Register REM query tools
    # from .tools import rem_query, ask_rem
    # mcp.tool()(rem_query)
    # mcp.tool()(ask_rem)

    # TODO: Register resource management tools
    # from .tools import create_resource, create_moment, update_graph_edges
    # mcp.tool()(create_resource)
    # mcp.tool()(create_moment)
    # mcp.tool()(update_graph_edges)

    # TODO: Register file operation tools
    # from .tools import upload_file, download_file
    # mcp.tool()(upload_file)
    # mcp.tool()(download_file)

    # TODO: Register schema resources
    # from .resources import register_schema_resources
    # register_schema_resources(mcp)

    # TODO: Register status resources
    # from .resources import register_status_resources
    # register_status_resources(mcp)

    return mcp
