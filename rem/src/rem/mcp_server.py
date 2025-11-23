"""
In-process MCP server for agent tool loading.

This module creates an MCP server instance that is imported directly by agents.
NO subprocess, NO stdio transport - just direct function calls in the same process.

The server exposes REM tools and resources that agents can call directly.
Services are initialized lazily on first tool call (see tools.py).
"""

import asyncio

from rem.api.mcp_router.server import create_mcp_server

# Create MCP server instance (is_local=True for local/in-process usage)
# No initialization needed - tools handle lazy init of services
mcp = create_mcp_server(is_local=True)


if __name__ == "__main__":
    # When run directly via CLI, start in stdio mode with service initialization
    from rem.api.mcp_router.tools import init_services
    from rem.services.postgres import get_postgres_service
    from rem.services.rem import RemService

    async def run_stdio():
        """Run MCP server in stdio mode with services."""
        db = get_postgres_service()
        if not db:
            raise RuntimeError("PostgreSQL service not available")
        await db.connect()
        rem_service = RemService(postgres_service=db)
        init_services(postgres_service=db, rem_service=rem_service)

        # Run server
        await mcp.run_async(transport="stdio")

        # Cleanup
        await db.disconnect()

    asyncio.run(run_stdio())
