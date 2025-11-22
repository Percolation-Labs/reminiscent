"""
REM MCP server command.

Run the FastMCP server in standalone mode (stdio transport for Claude Desktop).

Usage:
    rem mcp                 # Run MCP server in stdio mode
    rem mcp --http          # Run in HTTP mode (for testing)
"""

import click
from loguru import logger


@click.command("mcp")
@click.option(
    "--http",
    is_flag=True,
    help="Run in HTTP mode instead of stdio (for testing)",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind to (HTTP mode only)",
)
@click.option(
    "--port",
    default=8001,
    type=int,
    help="Port to listen on (HTTP mode only)",
)
def mcp_command(http: bool, host: str, port: int):
    """
    Run the REM MCP server.

    By default, runs in stdio mode for Claude Desktop integration.
    Use --http for testing in HTTP mode.

    Examples:
        # Stdio mode (for Claude Desktop)
        rem mcp

        # HTTP mode (for testing)
        rem mcp --http --port 8001
    """
    from rem.api.mcp_router.server import create_mcp_server

    # Stdio mode is local (allows local file paths), HTTP mode is remote (s3/https only)
    mcp = create_mcp_server(is_local=not http)

    if http:
        # HTTP mode for testing
        logger.info(f"Starting REM MCP server in HTTP mode at http://{host}:{port}")
        import uvicorn

        mcp_app = mcp.get_asgi_app()
        uvicorn.run(mcp_app, host=host, port=port)
    else:
        # Stdio mode for Claude Desktop
        logger.info("Starting REM MCP server in stdio mode (Claude Desktop)")
        mcp.run()


def register_command(cli_group):
    """Register the mcp command."""
    cli_group.add_command(mcp_command)
