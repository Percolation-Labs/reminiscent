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


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool):
    """REM - Resources Entities Moments system CLI."""
    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")


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

register_schema_commands(schema)
register_db_commands(db)
register_process_commands(process)
register_dreaming_commands(dreaming)
register_ask_command(cli)
register_configure_command(cli)
register_serve_command(cli)
register_mcp_command(cli)
cli.add_command(experiments_group)


def main():
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
