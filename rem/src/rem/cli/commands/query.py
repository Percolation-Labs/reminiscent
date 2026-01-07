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

    # Use connection string from settings to provide helpful error messages early
    logger.debug(f"Connecting to database: {settings.postgres.connection_string}")

    await db.connect()

    try:
        # If user_id provided and query touches the resources table, inject a parameterized filter
        if user_id:
            lower_sql = sql_text.lower()
            if re.search(r'\bfrom\s+resources\b', lower_sql) or re.search(r'\bjoin\s+resources\b', lower_sql):
                # Insert filter before ORDER BY / LIMIT / OFFSET / GROUP BY / HAVING if present
                tail_pattern = re.compile(r'\b(order\s+by|limit|offset|group\s+by|having)\b', re.IGNORECASE)
                m = tail_pattern.search(sql_text)
                if m:
                    main = sql_text[: m.start()]
                    tail = sql_text[m.start() :]
                else:
                    main = sql_text
                    tail = ""

                placeholder = f"${len(params) + 1}"
                if re.search(r'\bwhere\b', main, re.IGNORECASE):
                    main = main + f" AND user_id = {placeholder}"
                else:
                    main = main + f" WHERE user_id = {placeholder}"

                sql_text = main + tail
                params.append(user_id)

        # Print the final SQL and params that will be executed
        click.secho("SQL to execute:", fg="yellow")
        click.echo(sql_text)
        if params:
            click.echo(f"Params: {params}")

        # Decide whether this is a read (SELECT) or non-read statement.
        # For simplicity, use db.fetch which works for queries returning rows.
        rows = await db.fetch(sql_text, *params)

        # Convert asyncpg.Record to dicts if needed
        output_rows = []
        for row in rows:
            try:
                # asyncpg.Record behaves like a mapping
                output_rows.append(dict(row))
            except Exception:
                # Fallback - represent the record as-is
                output_rows.append(row)

        if as_json:
            click.echo(json.dumps(output_rows, default=str, indent=2))
        else:
            for r in output_rows:
                click.echo(str(r))

    finally:
        await db.disconnect()


def register_command(cli_group):
    """Register the query command on the given CLI group (top-level)."""
    cli_group.add_command(query_command)


