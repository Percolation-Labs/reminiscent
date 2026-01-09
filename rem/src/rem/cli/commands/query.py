"""
Simple SQL query command for REM.

Usage:
    rem query --sql "SELECT * FROM resources LIMIT 5"
    rem query --file migrations/001_init.sql

This tool connects to the configured PostgreSQL instance and executes the
provided SQL, printing results as JSON (default) or plain dicts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List
import re

import click
from loguru import logger
from ...services.rem.service import RemService
from ...services.rem.parser import RemQueryParser
from ...services.rem import QueryExecutionError
from ...models.core import RemQuery 

@click.command("query")
@click.option("--sql", "-s", default=None, help="SQL query string to execute")
@click.option(
    "--file",
    "-f",
    "sql_file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to SQL file to execute",
)

@click.option(
    "--param",
    "-p",
    "params",
    multiple=True,
    help="Query parameter (can be repeated for multiple params)",
)

@click.option("--no-json", is_flag=True, default=False, help="Print rows as Python dicts instead of JSON")
@click.option("--user-id", "-u", default=None, help="Scope query to a specific user (applies to resources table)")
def query_command(sql: str | None, sql_file: Path | None, params: List[str], no_json: bool, user_id: str | None):
    """
    Execute a SQL query against the REM PostgreSQL database.

    Either `--sql` or `--file` must be provided.
    """
    if not sql and not sql_file:
        click.secho("Error: either --sql or --file is required", fg="red")
        raise click.Abort()

    # Read SQL from file if provided
    if sql_file:
        sql_text = sql_file.read_text(encoding="utf-8")
    else:
        sql_text = sql  # type: ignore[assignment]

    try:
        # Pass mutable params list so _run_query_async can append the user_id parameter
        asyncio.run(_run_query_async(sql_text, list(params), not no_json, user_id))
    except Exception as exc:  # pragma: no cover - CLI error path
        logger.exception("Query failed")
        click.secho(f"✗ Query failed: {exc}", fg="red")
        raise click.Abort()


async def _run_query_async(sql_text: str, params: List[str], as_json: bool, user_id: str | None) -> None:
    """
    Async implementation: connect to Postgres service, run the query, print results.
    """
    from ...services.postgres import get_postgres_service
    from ...settings import settings

    db = get_postgres_service()
    if not db:
        click.secho("✗ PostgreSQL is disabled in settings. Enable with POSTGRES__ENABLED=true", fg="red")
        raise click.Abort()
    
    if db.pool is None:
        await db.connect()
        
    rem_service = RemService(db)
    

    query_parser = RemQueryParser()
    # Use connection string from settings to provide helpful error messages early
    query_type, parameters = query_parser.parse(sql_text)

    rem_query = RemQuery.model_validate({
        "query_type": query_type,
        "parameters": parameters,
        "user_id": user_id,
    })

    try:
        result = await rem_service.execute_query(rem_query)
        # Extract rows from the result dict returned by RemService.execute_query
        output_rows = result.get("results", [])
    except QueryExecutionError as qe:
        logger.exception("Query execution failed")
        click.secho(f"✗ Query execution failed: {qe}. Please check the query you provided and try again.", fg="red")
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


