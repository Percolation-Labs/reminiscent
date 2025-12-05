"""
REM CLI entry point.

Usage:
    rem db schema generate --models src/rem/models/entities
    rem db schema validate
    rem db migrate up
    rem dev run-server
"""

import sys
from pathlib import Path

import click
from loguru import logger

# Import version from package
try:
    from importlib.metadata import version
    __version__ = version("remdb")
except Exception:
    __version__ = "unknown"


def _configure_logger(level: str):
    """Configure loguru with custom level icons."""
    logger.remove()

    # Configure level icons - only warnings and errors get visual indicators
    logger.level("DEBUG", icon=" ")
    logger.level("INFO", icon=" ")
    logger.level("WARNING", icon="🟠")
    logger.level("ERROR", icon="🔴")
    logger.level("CRITICAL", icon="🔴")

    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | {level.icon} <level>{level: <8}</level> | <level>{message}</level>",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.version_option(version=__version__, prog_name="rem")
def cli(verbose: bool):
    """REM - Resources Entities Moments system CLI."""
    _configure_logger("DEBUG" if verbose else "INFO")


@cli.group()
def db():
    """Database operations (schema, migrate, status, etc.)."""
    pass


@db.group()
def schema():
    """Database schema management commands."""
    pass


@cli.group()
def dev():
    """Development utilities."""
    pass


@cli.group()
def process():
    """File processing commands."""
    pass


@cli.group()
def dreaming():
    """Memory indexing and knowledge extraction."""
    pass


@cli.group()
def cluster():
    """Kubernetes cluster deployment and management."""
    pass


# Register commands
from .commands.schema import register_commands as register_schema_commands
from .commands.db import register_commands as register_db_commands
from .commands.process import register_commands as register_process_commands
from .commands.ask import register_command as register_ask_command
from .commands.dreaming import register_commands as register_dreaming_commands
from .commands.experiments import experiments as experiments_group
from .commands.configure import register_command as register_configure_command
from .commands.serve import register_command as register_serve_command
from .commands.mcp import register_command as register_mcp_command
from .commands.scaffold import scaffold as scaffold_command
from .commands.cluster import register_commands as register_cluster_commands
from .commands.session import register_command as register_session_command

register_schema_commands(schema)
register_db_commands(db)
register_process_commands(process)
register_dreaming_commands(dreaming)
register_cluster_commands(cluster)
register_ask_command(cli)
register_configure_command(cli)
register_serve_command(cli)
register_mcp_command(cli)
cli.add_command(experiments_group)
cli.add_command(scaffold_command)
register_session_command(cli)


def main():
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
