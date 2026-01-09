"""
REM query command.

Usage:
    rem query --sql 'LOOKUP "Sarah Chen"'
    rem query --sql 'SEARCH resources "API design" LIMIT 10'
    rem query --sql "SELECT * FROM resources LIMIT 5"
    rem query --file queries/my_query.sql

This tool connects to the configured PostgreSQL instance and executes the
provided REM dialect query, printing results as JSON (default) or plain dicts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List

import click
from loguru import logger

from ...services.rem import QueryExecutionError
from ...services.rem.service import RemService


@click.command("query")
@click.option("--sql", "-s", default=None, help="REM query string (LOOKUP, SEARCH, FUZZY, TRAVERSE, or SQL)")
@click.option(
    "--file",
    "-f",
    "sql_file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to file containing REM query",
)
@click.option("--no-json", is_flag=True, default=False, help="Print rows as Python dicts instead of JSON")
@click.option("--user-id", "-u", default=None, help="Scope query to a specific user")
def query_command(sql: str | None, sql_file: Path | None, no_json: bool, user_id: str | None):
    """
    Execute a REM query against the database.

    Supports REM dialect queries (LOOKUP, SEARCH, FUZZY, TRAVERSE) and raw SQL.
    Either --sql or --file must be provided.
    """
    if not sql and not sql_file:
        click.secho("Error: either --sql or --file is required", fg="red")
        raise click.Abort()

    # Read query from file if provided
    if sql_file:
        query_text = sql_file.read_text(encoding="utf-8")
    else:
        query_text = sql  # type: ignore[assignment]

    try:
        asyncio.run(_run_query_async(query_text, not no_json, user_id))
    except Exception as exc:  # pragma: no cover - CLI error path
        logger.exception("Query failed")
        click.secho(f"✗ Query failed: {exc}", fg="red")
        raise click.Abort()


async def _run_query_async(query_text: str, as_json: bool, user_id: str | None) -> None:
    """
    Execute the query using RemService.execute_query_string().
    """
    from ...services.postgres import get_postgres_service

    db = get_postgres_service()
    if not db:
        click.secho("✗ PostgreSQL is disabled in settings. Enable with POSTGRES__ENABLED=true", fg="red")
        raise click.Abort()

    if db.pool is None:
        await db.connect()

    rem_service = RemService(db)

    try:
        # Use the unified execute_query_string method
        result = await rem_service.execute_query_string(query_text, user_id=user_id)
        output_rows = result.get("results", [])
    except QueryExecutionError as qe:
        logger.exception("Query execution failed")
        click.secho(f"✗ Query execution failed: {qe}. Please check the query you provided and try again.", fg="red")
        raise click.Abort()
    except ValueError as ve:
        # Parse errors from the query parser
        click.secho(f"✗ Invalid query: {ve}", fg="red")
        raise click.Abort()
    except Exception as exc:  # pragma: no cover - CLI error path
        logger.exception("Unexpected error during query execution")
        click.secho("✗ An unexpected error occurred while executing the query. Please check the query you provided and try again.", fg="red")
        raise click.Abort()

    if as_json:
        click.echo(json.dumps(output_rows, default=str, indent=2))
    else:
        for r in output_rows:
            click.echo(str(r))


def register_command(cli_group):
    """Register the query command on the given CLI group (top-level)."""
    cli_group.add_command(query_command)


