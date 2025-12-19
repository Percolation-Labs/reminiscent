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
from typing import Type

import click
from loguru import logger
from pydantic import BaseModel


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


async def run_sql_file_async(file_path: Path, db) -> tuple[bool, str, float]:
    """
    Execute a SQL file using psycopg3 (synchronous, handles multi-statement SQL).

    Args:
        file_path: Path to SQL file
        db: PostgresService instance (used to get connection info)

    Returns:
        Tuple of (success, output, execution_time_ms)
    """
    if not file_path.exists():
        return False, f"File not found: {file_path}", 0

    start_time = time.time()

    try:
        # Read SQL file
        sql_content = file_path.read_text(encoding="utf-8")

        # Use psycopg3 for reliable multi-statement execution
        # This is the synchronous PostgreSQL driver, perfect for migrations
        import psycopg
        from ...settings import settings

        # Use connection string from settings
        conn_str = settings.postgres.connection_string

        # Execute using synchronous psycopg (not async)
        # This properly handles multi-statement SQL scripts
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_content)
            conn.commit()

        execution_time = (time.time() - start_time) * 1000
        return True, f"Successfully executed {file_path.name}", execution_time

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        error_output = str(e)
        return False, error_output, execution_time


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of file."""
    if not file_path.exists():
        return ""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


@click.command()
@click.option(
    "--background-indexes",
    is_flag=True,
    help="Also apply background HNSW indexes (run after data load)",
)
def migrate(background_indexes: bool):
    """
    Apply standard database migrations (001_install + 002_install_models).

    This is a convenience command for initial setup. It applies:
    1. 001_install.sql - Core infrastructure (extensions, kv_store)
    2. 002_install_models.sql - Entity tables from registered models

    For incremental changes, use the diff-based workflow instead:
        rem db schema generate  # Regenerate from models
        rem db diff             # Check what changed
        rem db apply <file>     # Apply changes

    Examples:
        rem db migrate                    # Initial setup
        rem db migrate --background-indexes  # Include HNSW indexes
    """
    asyncio.run(_migrate_async(background_indexes))


async def _migrate_async(background_indexes: bool):
    """Async implementation of migrate command."""
    from ...settings import settings
    from ...utils.sql_paths import (
        get_package_sql_dir,
        get_user_sql_dir,
        list_all_migrations,
    )

    click.echo()
    click.echo("REM Database Migration")
    click.echo("=" * 60)

    # Find package SQL directory
    try:
        package_sql_dir = get_package_sql_dir()
        click.echo(f"Package SQL: {package_sql_dir}")
    except FileNotFoundError as e:
        click.secho(f"✗ {e}", fg="red")
        raise click.Abort()

    # Check for user migrations
    user_sql_dir = get_user_sql_dir()
    if user_sql_dir:
        click.echo(f"User SQL: {user_sql_dir}")

    # Get all migrations (package + user)
    all_migrations = list_all_migrations()

    if not all_migrations:
        click.secho("✗ No migration files found", fg="red")
        raise click.Abort()

    click.echo(f"Found {len(all_migrations)} migration(s)")
    click.echo()

    # Add background indexes if requested
    migrations_to_apply = [(f, f.stem) for f in all_migrations]

    if background_indexes:
        bg_indexes = package_sql_dir / "background_indexes.sql"
        if bg_indexes.exists():
            migrations_to_apply.append((bg_indexes, "Background Indexes"))
        else:
            click.secho("⚠ background_indexes.sql not found, skipping", fg="yellow")

    # Check all files exist (they should, but verify)
    for file_path, description in migrations_to_apply:
        if not file_path.exists():
            click.secho(f"✗ {file_path.name} not found", fg="red")
            if "002" in file_path.name:
                click.echo()
                click.secho("Generate it first with:", fg="yellow")
                click.secho("  rem db schema generate", fg="yellow")
            raise click.Abort()

    # Apply each migration
    import psycopg
    conn_str = settings.postgres.connection_string
    total_time = 0.0

    for file_path, description in migrations_to_apply:
        click.echo(f"Applying: {file_path.name}")

        sql_content = file_path.read_text(encoding="utf-8")
        start_time = time.time()

        try:
            with psycopg.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_content)
                conn.commit()

            exec_time = (time.time() - start_time) * 1000
            total_time += exec_time
            click.secho(f"  ✓ Applied in {exec_time:.0f}ms", fg="green")

        except Exception as e:
            click.secho(f"  ✗ Failed: {e}", fg="red")
            raise click.Abort()

        click.echo()

    click.echo("=" * 60)
    click.secho("✓ All migrations applied", fg="green")
    click.echo(f"  Total time: {total_time:.0f}ms")
    click.echo()
    click.echo("Next: verify with 'rem db diff'")


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
    asyncio.run(_status_async(connection))


async def _status_async(connection: str | None):
    """Async implementation of status command."""
    from ...services.postgres import get_postgres_service

    click.echo()
    click.echo("REM Migration Status")
    click.echo("=" * 60)

    db = get_postgres_service()
    if not db:
        click.secho("Error: PostgreSQL is disabled in settings.", fg="red")
        raise click.Abort()

    try:
        await db.connect()

        # Query migration status
        query = "SELECT * FROM migration_status();"

        try:
            rows = await db.fetch(query)

            if not rows:
                click.echo("No migrations found")
                click.echo()
                click.secho("Run: rem db migrate", fg="yellow")
                return

            # Display results
            click.echo()
            for row in rows:
                migration_type = row.get("migration_type", "unknown")
                count = row.get("count", 0)
                last_applied = row.get("last_applied", "never")
                total_time = row.get("total_time_ms", 0)

                click.echo(f"{migration_type.upper()}:")
                click.echo(f"  Count: {count}")
                click.echo(f"  Last Applied: {last_applied}")
                click.echo(f"  Total Time: {total_time}ms")
                click.echo()

        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str or "relation" in error_str or "function" in error_str:
                click.secho("✗ Migration tracking not found", fg="red")
                click.echo()
                click.secho("Run: rem db migrate", fg="yellow")
            else:
                click.secho(f"✗ Error: {error_str}", fg="red")
            raise click.Abort()

    finally:
        await db.disconnect()


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

        click.secho("✓ Cache rebuilt successfully", fg="green")

        # Show any NOTICE messages
        for line in result.stdout.split("\n") + result.stderr.split("\n"):
            if "NOTICE:" in line:
                notice = line.split("NOTICE:")[-1].strip()
                if notice:
                    click.echo(f"  {notice}")

    except subprocess.CalledProcessError as e:
        error = e.stderr or e.stdout or str(e)
        click.secho(f"✗ Error: {error}", fg="red")
        raise click.Abort()


@click.command()
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option("--table", "-t", default=None, help="Target table name (required for non-YAML formats)")
@click.option("--user-id", default=None, help="User ID to scope data privately (default: public/shared)")
@click.option("--dry-run", is_flag=True, help="Show what would be loaded without loading")
def load(file_path: Path, table: str | None, user_id: str | None, dry_run: bool):
    """
    Load data from file into database.

    Supports YAML with embedded metadata, or any tabular format via Polars
    (jsonl, parquet, csv, json, arrow, etc.). For non-YAML formats, use --table.

    Examples:
        rem db load data.yaml                        # YAML with metadata
        rem db load data.jsonl -t resources          # Any Polars-supported format
    """
    asyncio.run(_load_async(file_path, table, user_id, dry_run))


def _load_dataframe_from_file(file_path: Path) -> "pl.DataFrame":
    """Load any Polars-supported file format into a DataFrame."""
    import polars as pl

    suffix = file_path.suffix.lower()

    if suffix in {".jsonl", ".ndjson"}:
        return pl.read_ndjson(file_path)
    elif suffix in {".parquet", ".pq"}:
        return pl.read_parquet(file_path)
    elif suffix == ".csv":
        return pl.read_csv(file_path)
    elif suffix == ".json":
        return pl.read_json(file_path)
    elif suffix in {".ipc", ".arrow"}:
        return pl.read_ipc(file_path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use any Polars-supported format.")


async def _load_async(file_path: Path, table: str | None, user_id: str | None, dry_run: bool):
    """Async implementation of load command."""
    import polars as pl
    import yaml
    from ...models.core.inline_edge import InlineEdge
    from ...models.entities import SharedSession
    from ...services.postgres import get_postgres_service
    from ...utils.model_helpers import get_table_name
    from ... import get_model_registry

    logger.info(f"Loading data from: {file_path}")
    scope_msg = f"user: {user_id}" if user_id else "public"
    logger.info(f"Scope: {scope_msg}")

    suffix = file_path.suffix.lower()
    is_yaml = suffix in {".yaml", ".yml"}

    # Build MODEL_MAP dynamically from registry
    registry = get_model_registry()
    registry.register_core_models()
    MODEL_MAP = {
        get_table_name(model): model
        for model in registry.get_model_classes().values()
    }

    # Non-CoreModel tables that need direct SQL insertion
    DIRECT_INSERT_TABLES = {"shared_sessions"}

    # Parse file based on format
    if is_yaml:
        # YAML with embedded metadata
        with open(file_path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, list):
            logger.error("YAML must be a list of table definitions")
            raise click.Abort()

        if dry_run:
            logger.info("DRY RUN - Would load:")
            logger.info(yaml.dump(data, default_flow_style=False))
            return

        table_defs = data
    else:
        # Polars-supported format - require --table
        if not table:
            logger.error(f"For {suffix} files, --table is required. Example: rem db load {file_path.name} -t resources")
            raise click.Abort()

        try:
            df = _load_dataframe_from_file(file_path)
        except Exception as e:
            logger.error(f"Failed to load file: {e}")
            raise click.Abort()

        rows = df.to_dicts()

        if dry_run:
            logger.info(f"DRY RUN - Would load {len(rows)} rows to table '{table}':")
            logger.info(f"Columns: {list(df.columns)}")

            # Validate first row against model if table is known
            if table in MODEL_MAP and rows:
                from ...utils.model_helpers import validate_data_for_model
                result = validate_data_for_model(MODEL_MAP[table], rows[0])
                if result.extra_fields:
                    logger.warning(f"Unknown fields (ignored): {result.extra_fields}")
                if result.valid:
                    logger.success(f"Sample row validates OK. Required: {result.required_fields or '(none)'}")
                else:
                    result.log_errors("Sample row")
            return

        # Wrap as single table definition
        table_defs = [{"table": table, "rows": rows}]

    # Connect to database
    pg = get_postgres_service()
    if not pg:
        logger.error("PostgreSQL is disabled in settings. Enable with POSTGRES__ENABLED=true")
        raise click.Abort()

    await pg.connect()

    # Start embedding worker for generating embeddings
    if pg.embedding_worker:
        await pg.embedding_worker.start()

    try:
        total_loaded = 0

        for table_def in table_defs:
            table_name = table_def["table"]
            rows = table_def.get("rows", [])

            # Handle direct insert tables (non-CoreModel)
            if table_name in DIRECT_INSERT_TABLES:
                for row_data in rows:
                    # tenant_id is optional - NULL means public/shared

                    if table_name == "shared_sessions":
                        await pg.fetch(
                            """INSERT INTO shared_sessions
                               (session_id, owner_user_id, shared_with_user_id, tenant_id)
                               VALUES ($1, $2, $3, $4)
                               ON CONFLICT DO NOTHING""",
                            row_data["session_id"],
                            row_data["owner_user_id"],
                            row_data["shared_with_user_id"],
                            row_data.get("tenant_id"),  # Optional - NULL means public
                        )
                        total_loaded += 1
                        logger.success(f"Loaded shared_session: {row_data['owner_user_id']} -> {row_data['shared_with_user_id']}")
                continue

            if table_name not in MODEL_MAP:
                logger.warning(f"Unknown table: {table_name}, skipping")
                continue

            model_class = MODEL_MAP[table_name]

            for row_idx, row_data in enumerate(rows):
                # tenant_id and user_id are optional - NULL means public/shared data
                # Data files can explicitly set tenant_id/user_id if needed

                # Convert graph_edges to InlineEdge format if present
                if "graph_edges" in row_data:
                    row_data["graph_edges"] = [
                        InlineEdge(**edge).model_dump(mode='json')
                        for edge in row_data["graph_edges"]
                    ]

                # Convert ISO timestamp strings
                from ...utils.date_utils import parse_iso
                for key, value in list(row_data.items()):
                    if isinstance(value, str) and (key.endswith("_timestamp") or key.endswith("_at")):
                        try:
                            row_data[key] = parse_iso(value)
                        except (ValueError, TypeError):
                            pass

                from ...services.postgres.repository import Repository
                from ...utils.model_helpers import validate_data_for_model

                result = validate_data_for_model(model_class, row_data)
                if not result.valid:
                    result.log_errors(f"Row {row_idx + 1} ({table_name})")
                    raise click.Abort()

                repo = Repository(model_class, table_name, pg)
                await repo.upsert(result.instance)  # type: ignore[arg-type]
                total_loaded += 1

                name = getattr(result.instance, 'name', getattr(result.instance, 'id', '?'))
                logger.success(f"Loaded {table_name[:-1]}: {name}")

        logger.success(f"Data loaded successfully! Total rows: {total_loaded}")

        # Wait for embeddings to complete
        if pg.embedding_worker and pg.embedding_worker.running:
            queue_size = pg.embedding_worker.task_queue.qsize()
            if queue_size > 0:
                logger.info(f"Waiting for {queue_size} embeddings to complete...")
            await pg.embedding_worker.stop()
            logger.success("Embeddings generated successfully")

    finally:
        await pg.disconnect()


@click.command()
@click.option(
    "--check",
    is_flag=True,
    help="Exit with non-zero status if drift detected (for CI)",
)
@click.option(
    "--generate",
    is_flag=True,
    help="Generate incremental migration file from diff",
)
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(["additive", "full", "safe"]),
    default="additive",
    help="Migration strategy: additive (no drops, default), full (all changes), safe (additive + type widenings)",
)
@click.option(
    "--models",
    "-m",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory containing Pydantic models (default: auto-detect)",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for generated migration (default: sql/migrations)",
)
@click.option(
    "--message",
    default="schema_update",
    help="Migration message/description (used in filename)",
)
def diff(
    check: bool,
    generate: bool,
    strategy: str,
    models: Path | None,
    output_dir: Path | None,
    message: str,
):
    """
    Compare database schema against Pydantic models.

    Uses Alembic autogenerate to detect differences between:
    - Your Pydantic models (the target schema)
    - The current database (what's actually deployed)

    Strategies:
        additive  Only ADD columns/tables/indexes (safe, no data loss) [default]
        full      All changes including DROPs (use with caution)
        safe      Additive + safe column type changes (widenings only)

    Examples:
        rem db diff                        # Show additive changes only
        rem db diff --strategy full        # Show all changes including drops
        rem db diff --generate             # Create migration file
        rem db diff --check                # CI mode: exit 1 if drift

    Workflow:
        1. Develop locally, modify Pydantic models
        2. Run 'rem db diff' to see changes
        3. Run 'rem db diff --generate' to create migration
        4. Review generated SQL, then 'rem db apply <file>'
    """
    asyncio.run(_diff_async(check, generate, strategy, models, output_dir, message))


async def _diff_async(
    check: bool,
    generate: bool,
    strategy: str,
    models: Path | None,
    output_dir: Path | None,
    message: str,
):
    """Async implementation of diff command."""
    from ...services.postgres.diff_service import DiffService

    click.echo()
    click.echo("REM Schema Diff")
    click.echo("=" * 60)
    click.echo(f"Strategy: {strategy}")

    # Initialize diff service
    diff_service = DiffService(models_dir=models, strategy=strategy)

    try:
        # Compute diff
        click.echo("Comparing Pydantic models against database...")
        click.echo()

        result = diff_service.compute_diff()

        if not result.has_changes:
            click.secho("✓ No schema drift detected", fg="green")
            click.echo("  Database matches source (tables, functions, triggers, views)")
            if result.filtered_count > 0:
                click.echo()
                click.secho(f"  ({result.filtered_count} destructive change(s) hidden by '{strategy}' strategy)", fg="yellow")
                click.echo("  Use --strategy full to see all changes")
            return

        # Show changes
        click.secho(f"⚠ Schema drift detected: {result.change_count} change(s)", fg="yellow")
        if result.filtered_count > 0:
            click.secho(f"   ({result.filtered_count} destructive change(s) hidden by '{strategy}' strategy)", fg="yellow")
        click.echo()

        # Table/column changes (Alembic)
        if result.summary:
            click.echo("Table Changes:")
            for line in result.summary:
                if line.startswith("+"):
                    click.secho(f"  {line}", fg="green")
                elif line.startswith("-"):
                    click.secho(f"  {line}", fg="red")
                elif line.startswith("~"):
                    click.secho(f"  {line}", fg="yellow")
                else:
                    click.echo(f"  {line}")
            click.echo()

        # Programmable object changes (functions, triggers, views)
        if result.programmable_summary:
            click.echo("Programmable Objects (functions/triggers/views):")
            for line in result.programmable_summary:
                if line.startswith("+"):
                    click.secho(f"  {line}", fg="green")
                elif line.startswith("-"):
                    click.secho(f"  {line}", fg="red")
                elif line.startswith("~"):
                    click.secho(f"  {line}", fg="yellow")
                else:
                    click.echo(f"  {line}")
            click.echo()

        # Generate migration if requested
        if generate:
            # Determine output directory
            if output_dir is None:
                import importlib.resources
                try:
                    sql_ref = importlib.resources.files("rem") / "sql" / "migrations"
                    output_dir = Path(str(sql_ref))
                except AttributeError:
                    import rem
                    package_dir = Path(rem.__file__).parent.parent
                    output_dir = package_dir / "sql" / "migrations"

            click.echo(f"Generating migration to: {output_dir}")
            migration_path = diff_service.generate_migration_file(output_dir, message)

            if migration_path:
                click.secho(f"✓ Migration generated: {migration_path.name}", fg="green")
                click.echo()
                click.echo("Next steps:")
                click.echo("  1. Review the generated SQL file")
                click.echo("  2. Run: rem db apply <file>")
            else:
                click.echo("No migration file generated (no changes)")

        # CI check mode
        if check:
            click.echo()
            click.secho("✗ Schema drift detected (--check mode)", fg="red")
            raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        click.secho(f"✗ Error: {e}", fg="red")
        logger.exception("Diff failed")
        raise click.Abort()


@click.command()
@click.argument("sql_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--log/--no-log",
    default=True,
    help="Log migration to rem_migrations table (default: yes)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show SQL that would be executed without running it",
)
def apply(sql_file: Path, log: bool, dry_run: bool):
    """
    Apply a SQL file directly to the database.

    This is the simple, code-as-source-of-truth approach:
    - Pydantic models define the schema
    - `rem db diff` detects drift
    - `rem db diff --generate` creates migration SQL
    - `rem db apply <file>` runs it

    Examples:
        rem db apply migrations/004_add_field.sql
        rem db apply --dry-run migrations/004_add_field.sql
        rem db apply --no-log migrations/004_add_field.sql
    """
    asyncio.run(_apply_async(sql_file, log, dry_run))


async def _apply_async(sql_file: Path, log: bool, dry_run: bool):
    """Async implementation of apply command."""
    from ...services.postgres import get_postgres_service

    click.echo()
    click.echo(f"Applying: {sql_file.name}")
    click.echo("=" * 60)

    # Read SQL content
    sql_content = sql_file.read_text(encoding="utf-8")

    if dry_run:
        click.echo()
        click.echo("SQL to execute (dry run):")
        click.echo("-" * 40)
        click.echo(sql_content)
        click.echo("-" * 40)
        click.echo()
        click.secho("Dry run - no changes made", fg="yellow")
        return

    # Execute SQL
    db = get_postgres_service()
    if not db:
        click.secho("✗ Could not connect to database", fg="red")
        raise click.Abort()

    start_time = time.time()

    try:
        import psycopg
        from ...settings import settings

        conn_str = settings.postgres.connection_string

        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_content)
            conn.commit()

            # Log to rem_migrations if requested
            if log:
                checksum = calculate_checksum(sql_file)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rem_migrations (name, type, checksum, applied_by)
                        VALUES (%s, 'diff', %s, CURRENT_USER)
                        ON CONFLICT (name) DO UPDATE SET
                            applied_at = CURRENT_TIMESTAMP,
                            checksum = EXCLUDED.checksum
                        """,
                        (sql_file.name, checksum[:16]),
                    )
                conn.commit()

        execution_time = (time.time() - start_time) * 1000
        click.secho(f"✓ Applied successfully in {execution_time:.0f}ms", fg="green")

        if log:
            click.echo(f"  Logged to rem_migrations as '{sql_file.name}'")

    except Exception as e:
        click.secho(f"✗ Failed: {e}", fg="red")
        raise click.Abort()


def register_commands(db_group):
    """Register all db commands."""
    db_group.add_command(migrate)
    db_group.add_command(status)
    db_group.add_command(rebuild_cache, name="rebuild-cache")
    db_group.add_command(load)
    db_group.add_command(diff)
    db_group.add_command(apply)
