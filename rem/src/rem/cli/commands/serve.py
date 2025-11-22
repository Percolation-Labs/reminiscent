"""
REM API server command.

Start the FastAPI server with uvicorn.

Usage:
    rem serve                   # Start API server with default settings
    rem serve --host 0.0.0.0    # Bind to all interfaces
    rem serve --port 8080       # Use custom port
    rem serve --reload          # Enable auto-reload (development)
    rem serve --workers 4       # Production mode with workers
"""

import click
from loguru import logger


@click.command("serve")
@click.option(
    "--host",
    default=None,
    help="Host to bind to (overrides config/env)",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port to listen on (overrides config/env)",
)
@click.option(
    "--reload",
    is_flag=True,
    default=None,
    help="Enable auto-reload for development",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of worker processes (production mode)",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
    help="Logging level",
)
def serve_command(
    host: str | None,
    port: int | None,
    reload: bool | None,
    workers: int | None,
    log_level: str | None,
):
    """
    Start the REM API server.

    The server will load configuration from:
    1. Environment variables (highest priority)
    2. ~/.rem/config.yaml (user configuration)
    3. Default values (lowest priority)

    Examples:
        rem serve                       # Use settings from config
        rem serve --host 0.0.0.0        # Bind to all interfaces
        rem serve --reload              # Development mode
        rem serve --workers 4           # Production mode (4 workers)
    """
    import uvicorn

    # Import settings to trigger config loading
    from rem.settings import settings

    # Build uvicorn config
    uvicorn_config = {
        "app": "rem.api.main:app",
        "host": host or settings.api.host,
        "port": port or settings.api.port,
        "log_level": log_level or settings.api.log_level,
    }

    # Reload or workers (mutually exclusive)
    if reload is not None:
        uvicorn_config["reload"] = reload
    elif workers is not None:
        uvicorn_config["workers"] = workers
    else:
        # Use settings defaults
        if settings.api.reload:
            uvicorn_config["reload"] = True
        else:
            uvicorn_config["workers"] = settings.api.workers

    # Start server
    logger.info(f"Starting REM API server at http://{uvicorn_config['host']}:{uvicorn_config['port']}")
    uvicorn.run(**uvicorn_config)


def register_command(cli_group):
    """Register the serve command."""
    cli_group.add_command(serve_command)
