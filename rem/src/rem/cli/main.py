"""
REM CLI entry point.

Usage:
    rem schema generate --models src/rem/models/entities --output sql/schema.sql
    rem schema validate
    rem migrate up
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
def schema():
    """Database schema management commands."""
    pass


@cli.group()
def db():
    """Database operations (migrate, status, etc.)."""
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
from .commands.phoenix import register_command as register_phoenix_command
from .commands.dreaming import register_commands as register_dreaming_commands

register_schema_commands(schema)
register_db_commands(db)
register_process_commands(process)
register_dreaming_commands(dreaming)
register_ask_command(cli)
register_phoenix_command(cli)


def main():
    """Main entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
