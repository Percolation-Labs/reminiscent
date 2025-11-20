"""
Database management commands.

Usage:
    rem db migrate                    # Apply both install.sql and install_models.sql
    rem db migrate --install          # Apply only install.sql
    rem db migrate --models           # Apply only install_models.sql
    rem db migrate --background-indexes  # Apply background indexes
    rem db status                     # Show migration status
    rem db rebuild-cache              # Rebuild KV_STORE cache
"""

import asyncio
import hashlib
import subprocess
import time
from pathlib import Path

import click
from loguru import logger


def get_connection_string() -> str:
    """
    Get PostgreSQL connection string from environment or settings.

    Returns:
        Connection string for psql
    """
    import os

    # Try environment variables first
    host = os.getenv("POSTGRES__HOST", "localhost")
    port = os.getenv("POSTGRES__PORT", "5432")
    database = os.getenv("POSTGRES__DATABASE", "remdb")
    user = os.getenv("POSTGRES__USER", "postgres")
    password = os.getenv("POSTGRES__PASSWORD", "")

    # Build connection string
    conn_str = f"host={host} port={port} dbname={database} user={user}"
    if password:
        conn_str += f" password={password}"

    return conn_str


def run_sql_file(file_path: Path, conn_str: str) -> tuple[bool, str, float]:
    """
    Execute a SQL file using psql.

    Args:
        file_path: Path to SQL file
        conn_str: PostgreSQL connection string

    Returns:
        Tuple of (success, output, execution_time_ms)
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}", 0

    start_time = time.time()

    try:
        result = subprocess.run(
            ["psql", conn_str, "-f", str(file_path), "-v", "ON_ERROR_STOP=1"],
            capture_output=True,
            text=True,
            check=True,
        )

        execution_time = (time.time() - start_time) * 1000
        return True, result.stdout + result.stderr, execution_time

    except subprocess.CalledProcessError as e:
        execution_time = (time.time() - start_time) * 1000
        error_output = e.stderr or e.stdout or str(e)
        return False, error_output, execution_time
    except FileNotFoundError:
        return False, "psql command not found. Ensure PostgreSQL client is installed.", 0


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of file."""
    if not file_path.exists():
        return ""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


@click.command()
@click.option(
    "--install",
    "install_only",
    is_flag=True,
    help="Apply only install.sql (extensions and infrastructure)",
)
@click.option(
    "--models", "models_only", is_flag=True, help="Apply only install_models.sql (entity tables)"
)
@click.option(
    "--background-indexes",
    is_flag=True,
    help="Apply background indexes (HNSW for vectors)",
)
@click.option(
    "--connection",
    "-c",
    help="PostgreSQL connection string (overrides environment)",
)
@click.option(
    "--sql-dir",
    type=click.Path(exists=True, path_type=Path),
    default="sql",
    help="Directory containing SQL files",
)
def migrate(
    install_only: bool,
    models_only: bool,
    background_indexes: bool,
    connection: str | None,
    sql_dir: Path,
):
    """
    Apply database migrations.

    By default, applies both install.sql and install_models.sql.
    Use flags to apply specific migrations.

    Examples:
        rem db migrate                     # Apply all
        rem db migrate --install           # Core infrastructure only
        rem db migrate --models            # Entity tables only
        rem db migrate --background-indexes  # Background HNSW indexes
    """
    conn_str = connection or get_connection_string()

    click.echo("REM Database Migration")
    click.echo("=" * 60)
    click.echo(f"SQL Directory: {sql_dir}")
    click.echo(f"Connection: {conn_str.split('password')[0]}...")
    click.echo()

    migrations = []

    # Determine which migrations to apply
    if background_indexes:
        migrations.append(("background_indexes.sql", "Background Indexes"))
    elif install_only:
        migrations.append(("install.sql", "Core Infrastructure"))
    elif models_only:
        migrations.append(("install_models.sql", "Entity Tables"))
    else:
        # Default: apply both install and models
        migrations.append(("install.sql", "Core Infrastructure"))
        migrations.append(("install_models.sql", "Entity Tables"))

    # Check files exist
    for filename, description in migrations:
        file_path = sql_dir / filename
        if not file_path.exists():
            if filename == "install_models.sql":
                click.echo(f"✗ {filename} not found", fg="red")
                click.echo()
                click.echo("Generate it first with:", fg="yellow")
                click.echo("  rem schema generate --models src/rem/models/entities", fg="yellow")
                raise click.Abort()
            else:
                click.echo(f"✗ {filename} not found", fg="red")
                raise click.Abort()

    # Apply migrations
    total_time = 0
    all_success = True

    for filename, description in migrations:
        file_path = sql_dir / filename
        checksum = calculate_checksum(file_path)

        click.echo(f"Applying: {description} ({filename})")
        click.echo(f"  Checksum: {checksum[:16]}...")

        success, output, exec_time = run_sql_file(file_path, conn_str)
        total_time += exec_time

        if success:
            click.echo(f"  ✓ Applied in {exec_time:.0f}ms", fg="green")
            # Show any NOTICE messages from the output
            for line in output.split("\n"):
                if "NOTICE:" in line or "✓" in line:
                    notice = line.split("NOTICE:")[-1].strip()
                    if notice:
                        click.echo(f"    {notice}")
        else:
            click.echo(f"  ✗ Failed", fg="red")
            click.echo()
            click.echo("Error output:", fg="red")
            click.echo(output, fg="red")
            all_success = False
            break

        click.echo()

    # Summary
    click.echo("=" * 60)
    if all_success:
        click.echo(f"✓ All migrations applied successfully", fg="green")
        click.echo(f"  Total time: {total_time:.0f}ms")
    else:
        click.echo(f"✗ Migration failed", fg="red")
        raise click.Abort()


@click.command()
@click.option(
    "--connection",
    "-c",
    help="PostgreSQL connection string (overrides environment)",
)
def status(connection: str | None):
    """
    Show migration status.

    Displays:
    - Applied migrations
    - Execution times
    - Last applied timestamps
    """
    conn_str = connection or get_connection_string()

    click.echo("REM Migration Status")
    click.echo("=" * 60)

    # Query migration status
    query = "SELECT * FROM migration_status();"

    try:
        result = subprocess.run(
            ["psql", conn_str, "-c", query, "-t", "-A", "-F", "|"],
            capture_output=True,
            text=True,
            check=True,
        )

        lines = result.stdout.strip().split("\n")
        if not lines or not lines[0]:
            click.echo("No migrations found")
            click.echo()
            click.echo("Run: rem db migrate --install", fg="yellow")
            return

        # Parse and display results
        click.echo()
        for line in lines:
            if "|" not in line:
                continue

            parts = line.split("|")
            if len(parts) >= 4:
                migration_type, count, last_applied, total_time = parts
                click.echo(f"{migration_type.upper()}:")
                click.echo(f"  Count: {count}")
                click.echo(f"  Last Applied: {last_applied}")
                click.echo(f"  Total Time: {total_time}ms")
                click.echo()

    except subprocess.CalledProcessError as e:
        error = e.stderr or e.stdout or str(e)
        if "does not exist" in error or "relation" in error:
            click.echo("✗ Migration table not found", fg="red")
            click.echo()
            click.echo("Run: rem db migrate --install", fg="yellow")
        else:
            click.echo(f"✗ Error: {error}", fg="red")
        raise click.Abort()


@click.command()
@click.option(
    "--connection",
    "-c",
    help="PostgreSQL connection string (overrides environment)",
)
def rebuild_cache(connection: str | None):
    """
    Rebuild KV_STORE cache from entity tables.

    Call this after:
    - Database restart (UNLOGGED tables are cleared)
    - Manual cache invalidation
    - Bulk data imports
    """
    conn_str = connection or get_connection_string()

    click.echo("Rebuilding KV_STORE cache...")

    query = "SELECT rebuild_kv_store();"

    try:
        result = subprocess.run(
            ["psql", conn_str, "-c", query],
            capture_output=True,
            text=True,
            check=True,
        )

        click.echo("✓ Cache rebuilt successfully", fg="green")

        # Show any NOTICE messages
        for line in result.stdout.split("\n") + result.stderr.split("\n"):
            if "NOTICE:" in line:
                notice = line.split("NOTICE:")[-1].strip()
                if notice:
                    click.echo(f"  {notice}")

    except subprocess.CalledProcessError as e:
        error = e.stderr or e.stdout or str(e)
        click.echo(f"✗ Error: {error}", fg="red")
        raise click.Abort()


def register_commands(db_group):
    """Register all db commands."""
    db_group.add_command(migrate)
    db_group.add_command(status)
    db_group.add_command(rebuild_cache, name="rebuild-cache")
