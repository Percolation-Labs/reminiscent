"""
Schema diff service for comparing Pydantic models against database.

Uses Alembic autogenerate to detect differences between:
- Target schema (derived from Pydantic models)
- Current database schema

Also compares programmable objects (functions, triggers, views) which
Alembic does not track.

This enables:
1. Local development: See what would change before applying migrations
2. CI validation: Detect drift between code and database (--check mode)
3. Migration generation: Create incremental migration files
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import io

from alembic.autogenerate import produce_migrations, render_python_code
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from ...settings import settings
from .pydantic_to_sqlalchemy import get_target_metadata


# Tables that are NOT managed by Pydantic models (infrastructure tables)
# These are created by 001_install.sql and should be excluded from diff
INFRASTRUCTURE_TABLES = {
    "kv_store",
    "rem_migrations",
    "rate_limits",
    "persons",  # Legacy table - to be removed from DB
}

# Prefixes for tables that should be included in diff
# (embeddings tables are created alongside entity tables)
EMBEDDINGS_PREFIX = "embeddings_"


@dataclass
class SchemaDiff:
    """Result of schema comparison."""

    has_changes: bool
    summary: list[str] = field(default_factory=list)
    sql: str = ""
    upgrade_ops: Optional[ops.UpgradeOps] = None
    filtered_count: int = 0  # Number of operations filtered out by strategy
    # Programmable objects (functions, triggers, views)
    programmable_summary: list[str] = field(default_factory=list)
    programmable_sql: str = ""

    @property
    def change_count(self) -> int:
        """Total number of detected changes."""
        return len(self.summary) + len(self.programmable_summary)


class DiffService:
    """
    Service for comparing Pydantic models against database schema.

    Uses Alembic's autogenerate machinery without creating revision files.

    Strategies:
        additive: Only ADD operations (columns, tables, indexes). No drops. Safe for production.
        full: All operations including DROPs. Use with caution.
        safe: Additive + safe column type changes (widenings like VARCHAR(50) -> VARCHAR(256)).
    """

    def __init__(self, models_dir: Optional[Path] = None, strategy: str = "additive"):
        """
        Initialize diff service.

        Args:
            models_dir: Directory containing Pydantic models.
                       If None, uses default rem/models/entities location.
            strategy: Migration strategy - 'additive' (default), 'full', or 'safe'
        """
        self.models_dir = models_dir
        self.strategy = strategy
        self._metadata = None

    def get_connection_url(self) -> str:
        """Build PostgreSQL connection URL from settings using psycopg (v3) driver."""
        pg = settings.postgres
        # Use postgresql+psycopg to use psycopg v3 (not psycopg2)
        url = f"postgresql+psycopg://{pg.user}"
        if pg.password:
            url += f":{pg.password}"
        url += f"@{pg.host}:{pg.port}/{pg.database}"
        return url

    def get_target_metadata(self):
        """Get SQLAlchemy metadata from Pydantic models."""
        if self._metadata is None:
            if self.models_dir:
                from .pydantic_to_sqlalchemy import build_sqlalchemy_metadata_from_pydantic
                self._metadata = build_sqlalchemy_metadata_from_pydantic(self.models_dir)
            else:
                self._metadata = get_target_metadata()
        return self._metadata

    def _include_object(self, obj, name, type_, reflected, compare_to) -> bool:
        """
        Filter function for Alembic autogenerate.

        Excludes infrastructure tables that are not managed by Pydantic models.

        Args:
            obj: The schema object (Table, Column, Index, etc.)
            name: Object name
            type_: Object type ("table", "column", "index", etc.)
            reflected: True if object exists in database
            compare_to: The object being compared to (if any)

        Returns:
            True to include in diff, False to exclude
        """
        if type_ == "table":
            # Exclude infrastructure tables
            if name in INFRASTRUCTURE_TABLES:
                return False
            # Include embeddings tables (they're part of the model schema)
            # These are now generated in pydantic_to_sqlalchemy
        return True

    def compute_diff(self, include_programmable: bool = True) -> SchemaDiff:
        """
        Compare Pydantic models against database and return differences.

        Args:
            include_programmable: If True, also diff functions/triggers/views

        Returns:
            SchemaDiff with detected changes
        """
        url = self.get_connection_url()
        engine = create_engine(url)
        metadata = self.get_target_metadata()

        summary = []
        filtered_count = 0

        with engine.connect() as conn:
            # Create migration context for comparison
            context = MigrationContext.configure(
                conn,
                opts={
                    "target_metadata": metadata,
                    "compare_type": True,
                    "compare_server_default": False,  # Avoid false positives
                    "include_schemas": False,
                    "include_object": self._include_object,
                },
            )

            # Run autogenerate comparison
            migration_script = produce_migrations(context, metadata)
            upgrade_ops = migration_script.upgrade_ops

            # Filter operations based on strategy
            if upgrade_ops and upgrade_ops.ops:
                filtered_ops, filtered_count = self._filter_operations(upgrade_ops.ops)
                upgrade_ops.ops = filtered_ops

                # Process filtered operations
                for op in filtered_ops:
                    summary.extend(self._describe_operation(op))

        # Generate SQL if there are changes
        sql = ""
        if summary and upgrade_ops:
            sql = self._render_sql(upgrade_ops, engine)

        # Programmable objects diff (functions, triggers, views)
        programmable_summary = []
        programmable_sql = ""
        if include_programmable:
            prog_summary, prog_sql = self._compute_programmable_diff()
            programmable_summary = prog_summary
            programmable_sql = prog_sql

        has_changes = len(summary) > 0 or len(programmable_summary) > 0

        return SchemaDiff(
            has_changes=has_changes,
            summary=summary,
            sql=sql,
            upgrade_ops=upgrade_ops,
            filtered_count=filtered_count,
            programmable_summary=programmable_summary,
            programmable_sql=programmable_sql,
        )

    def _compute_programmable_diff(self) -> tuple[list[str], str]:
        """
        Compute diff for programmable objects (functions, triggers, views).

        Returns:
            Tuple of (summary_lines, sync_sql)
        """
        from .programmable_diff_service import ProgrammableDiffService

        service = ProgrammableDiffService()

        # Run async diff in sync context
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(service.compute_diff())

        summary = []
        for diff in result.diffs:
            if diff.status == "missing":
                summary.append(f"+ {diff.object_type.value.upper()} {diff.name} (missing)")
            elif diff.status == "different":
                summary.append(f"~ {diff.object_type.value.upper()} {diff.name} (different)")
            elif diff.status == "extra":
                summary.append(f"- {diff.object_type.value.upper()} {diff.name} (extra in db)")

        return summary, result.sync_sql

    def _filter_operations(self, operations: list) -> tuple[list, int]:
        """
        Filter operations based on migration strategy.

        Args:
            operations: List of Alembic operations

        Returns:
            Tuple of (filtered_operations, count_of_filtered_out)
        """
        if self.strategy == "full":
            # Full strategy: include everything
            return operations, 0

        filtered = []
        filtered_count = 0

        for op in operations:
            if isinstance(op, ops.ModifyTableOps):
                # Filter sub-operations within table
                sub_filtered, sub_count = self._filter_operations(op.ops)
                filtered_count += sub_count
                if sub_filtered:
                    op.ops = sub_filtered
                    filtered.append(op)
            elif self._is_allowed_operation(op):
                filtered.append(op)
            else:
                filtered_count += 1

        return filtered, filtered_count

    def _is_allowed_operation(self, op: ops.MigrateOperation) -> bool:
        """
        Check if an operation is allowed by the current strategy.

        Args:
            op: Alembic operation

        Returns:
            True if operation is allowed, False if it should be filtered out
        """
        # Additive operations (allowed in all strategies)
        if isinstance(op, (ops.CreateTableOp, ops.AddColumnOp, ops.CreateIndexOp, ops.CreateForeignKeyOp)):
            return True

        # Destructive operations (only allowed in 'full' strategy)
        if isinstance(op, (ops.DropTableOp, ops.DropColumnOp, ops.DropIndexOp, ops.DropConstraintOp)):
            return self.strategy == "full"

        # Alter operations
        if isinstance(op, ops.AlterColumnOp):
            if self.strategy == "full":
                return True
            if self.strategy == "safe":
                # Allow safe type changes (widenings)
                return self._is_safe_type_change(op)
            # additive: no alter operations
            return False

        # Unknown operations: allow in full, deny otherwise
        return self.strategy == "full"

    def _is_safe_type_change(self, op: ops.AlterColumnOp) -> bool:
        """
        Check if a column type change is safe (widening, not narrowing).

        Safe changes:
        - VARCHAR(n) -> VARCHAR(m) where m > n
        - INTEGER -> BIGINT
        - Adding nullable (NOT NULL -> NULL)

        Args:
            op: AlterColumnOp to check

        Returns:
            True if the change is safe
        """
        # Allowing nullable is always safe
        if op.modify_nullable is True:
            return True

        # Type changes: only allow VARCHAR widenings for now
        if op.modify_type is not None:
            new_type = str(op.modify_type).upper()
            # VARCHAR widenings are generally safe
            if "VARCHAR" in new_type:
                return True  # Assume widening; could add length comparison

        return False

    def _describe_operation(self, op: ops.MigrateOperation, prefix: str = "") -> list[str]:
        """Convert Alembic operation to human-readable description."""
        descriptions = []

        if isinstance(op, ops.CreateTableOp):
            descriptions.append(f"{prefix}+ CREATE TABLE {op.table_name}")
            for col in op.columns:
                if hasattr(col, 'name'):
                    descriptions.append(f"{prefix}    + column {col.name}")

        elif isinstance(op, ops.DropTableOp):
            descriptions.append(f"{prefix}- DROP TABLE {op.table_name}")

        elif isinstance(op, ops.AddColumnOp):
            col_type = str(op.column.type) if op.column.type else "unknown"
            descriptions.append(f"{prefix}+ ADD COLUMN {op.table_name}.{op.column.name} ({col_type})")

        elif isinstance(op, ops.DropColumnOp):
            descriptions.append(f"{prefix}- DROP COLUMN {op.table_name}.{op.column_name}")

        elif isinstance(op, ops.AlterColumnOp):
            changes = []
            if op.modify_type is not None:
                changes.append(f"type -> {op.modify_type}")
            if op.modify_nullable is not None:
                nullable = "NULL" if op.modify_nullable else "NOT NULL"
                changes.append(f"nullable -> {nullable}")
            if op.modify_server_default is not None:
                changes.append(f"default -> {op.modify_server_default}")
            change_str = ", ".join(changes) if changes else "modified"
            descriptions.append(f"{prefix}~ ALTER COLUMN {op.table_name}.{op.column_name} ({change_str})")

        elif isinstance(op, ops.CreateIndexOp):
            # op.columns can be strings or Column objects
            if op.columns:
                cols = ", ".join(
                    c if isinstance(c, str) else getattr(c, 'name', str(c))
                    for c in op.columns
                )
            else:
                cols = "?"
            descriptions.append(f"{prefix}+ CREATE INDEX {op.index_name} ON {op.table_name} ({cols})")

        elif isinstance(op, ops.DropIndexOp):
            descriptions.append(f"{prefix}- DROP INDEX {op.index_name}")

        elif isinstance(op, ops.CreateForeignKeyOp):
            descriptions.append(f"{prefix}+ CREATE FK {op.constraint_name} ON {op.source_table}")

        elif isinstance(op, ops.DropConstraintOp):
            descriptions.append(f"{prefix}- DROP CONSTRAINT {op.constraint_name} ON {op.table_name}")

        elif isinstance(op, ops.ModifyTableOps):
            # Container for multiple operations on same table
            descriptions.append(f"{prefix}Table: {op.table_name}")
            for sub_op in op.ops:
                descriptions.extend(self._describe_operation(sub_op, prefix + "  "))

        else:
            descriptions.append(f"{prefix}? {type(op).__name__}")

        return descriptions

    def _render_sql(self, upgrade_ops: ops.UpgradeOps, engine) -> str:
        """Render upgrade operations as SQL statements."""
        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations

        sql_lines = []

        # Use offline mode to generate SQL
        buffer = io.StringIO()

        def emit_sql(text, *args, **kwargs):
            sql_lines.append(str(text))

        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "as_sql": True,
                    "output_buffer": buffer,
                    "target_metadata": self.get_target_metadata(),
                },
            )

            with context.begin_transaction():
                operations = Operations(context)
                for op in upgrade_ops.ops:
                    self._execute_op(operations, op)

        return buffer.getvalue()

    def _execute_op(self, operations: "Operations", op: ops.MigrateOperation):
        """Execute a single operation via Operations proxy."""
        from alembic.operations import Operations
        from alembic.autogenerate import rewriter

        if isinstance(op, ops.CreateTableOp):
            operations.create_table(
                op.table_name,
                *op.columns,
                schema=op.schema,
                **op.kw,
            )
        elif isinstance(op, ops.DropTableOp):
            operations.drop_table(op.table_name, schema=op.schema)
        elif isinstance(op, ops.AddColumnOp):
            operations.add_column(op.table_name, op.column, schema=op.schema)
        elif isinstance(op, ops.DropColumnOp):
            operations.drop_column(op.table_name, op.column_name, schema=op.schema)
        elif isinstance(op, ops.AlterColumnOp):
            operations.alter_column(
                op.table_name,
                op.column_name,
                nullable=op.modify_nullable,
                type_=op.modify_type,
                server_default=op.modify_server_default,
                schema=op.schema,
            )
        elif isinstance(op, ops.CreateIndexOp):
            operations.create_index(
                op.index_name,
                op.table_name,
                op.columns,
                schema=op.schema,
                unique=op.unique,
                **op.kw,
            )
        elif isinstance(op, ops.DropIndexOp):
            operations.drop_index(op.index_name, table_name=op.table_name, schema=op.schema)
        elif isinstance(op, ops.ModifyTableOps):
            for sub_op in op.ops:
                self._execute_op(operations, sub_op)

    def generate_migration_file(
        self,
        output_dir: Path,
        message: str = "auto_migration",
    ) -> Optional[Path]:
        """
        Generate a numbered migration file from the diff.

        Args:
            output_dir: Directory to write migration file
            message: Migration description (used in filename)

        Returns:
            Path to generated file, or None if no changes
        """
        diff = self.compute_diff()

        if not diff.has_changes:
            logger.info("No schema changes detected")
            return None

        # Find next migration number
        existing = sorted(output_dir.glob("*.sql"))
        next_num = 1
        for f in existing:
            try:
                num = int(f.stem.split("_")[0])
                next_num = max(next_num, num + 1)
            except (ValueError, IndexError):
                pass

        # Generate filename
        safe_message = message.replace(" ", "_").replace("-", "_")[:40]
        filename = f"{next_num:03d}_{safe_message}.sql"
        output_path = output_dir / filename

        # Write SQL
        header = f"""-- Migration: {message}
-- Generated by: rem db diff --generate
-- Changes detected: {diff.change_count}
--
-- Review this file before applying!
-- Apply with: rem db migrate
--

"""
        # Build SQL from operations
        sql_content = self._build_migration_sql(diff)

        output_path.write_text(header + sql_content)
        logger.info(f"Generated migration: {output_path}")

        return output_path

    def _build_migration_sql(self, diff: SchemaDiff) -> str:
        """Build SQL from diff operations."""
        if not diff.upgrade_ops or not diff.upgrade_ops.ops:
            return "-- No changes\n"

        lines = []
        for op in diff.upgrade_ops.ops:
            lines.extend(self._op_to_sql(op))

        return "\n".join(lines) + "\n"

    def _compile_type(self, col_type) -> str:
        """Compile SQLAlchemy type to PostgreSQL DDL string.

        SQLAlchemy types like ARRAY(Text) need dialect-specific compilation
        to render correctly (e.g., "TEXT[]" instead of just "ARRAY").
        """
        try:
            return col_type.compile(dialect=postgresql.dialect())
        except Exception:
            # Fallback to string representation if compilation fails
            return str(col_type)

    def _op_to_sql(self, op: ops.MigrateOperation) -> list[str]:
        """Convert operation to SQL statements."""
        lines = []

        if isinstance(op, ops.CreateTableOp):
            cols = []
            for col in op.columns:
                if hasattr(col, 'name') and hasattr(col, 'type'):
                    nullable = "" if getattr(col, 'nullable', True) else " NOT NULL"
                    type_str = self._compile_type(col.type)
                    cols.append(f"    {col.name} {type_str}{nullable}")
            col_str = ",\n".join(cols)
            lines.append(f"CREATE TABLE IF NOT EXISTS {op.table_name} (\n{col_str}\n);")

        elif isinstance(op, ops.DropTableOp):
            lines.append(f"DROP TABLE IF EXISTS {op.table_name};")

        elif isinstance(op, ops.AddColumnOp):
            col = op.column
            nullable = "" if getattr(col, 'nullable', True) else " NOT NULL"
            type_str = self._compile_type(col.type)
            lines.append(f"ALTER TABLE {op.table_name} ADD COLUMN IF NOT EXISTS {col.name} {type_str}{nullable};")

        elif isinstance(op, ops.DropColumnOp):
            lines.append(f"ALTER TABLE {op.table_name} DROP COLUMN IF EXISTS {op.column_name};")

        elif isinstance(op, ops.AlterColumnOp):
            if op.modify_type is not None:
                type_str = self._compile_type(op.modify_type)
                lines.append(f"ALTER TABLE {op.table_name} ALTER COLUMN {op.column_name} TYPE {type_str};")
            if op.modify_nullable is not None:
                if op.modify_nullable:
                    lines.append(f"ALTER TABLE {op.table_name} ALTER COLUMN {op.column_name} DROP NOT NULL;")
                else:
                    lines.append(f"ALTER TABLE {op.table_name} ALTER COLUMN {op.column_name} SET NOT NULL;")

        elif isinstance(op, ops.CreateIndexOp):
            # op.columns can be strings or Column objects
            if op.columns:
                cols = ", ".join(
                    c if isinstance(c, str) else getattr(c, 'name', str(c))
                    for c in op.columns
                )
            else:
                cols = ""
            unique = "UNIQUE " if op.unique else ""
            lines.append(f"CREATE {unique}INDEX IF NOT EXISTS {op.index_name} ON {op.table_name} ({cols});")

        elif isinstance(op, ops.DropIndexOp):
            lines.append(f"DROP INDEX IF EXISTS {op.index_name};")

        elif isinstance(op, ops.ModifyTableOps):
            lines.append(f"-- Changes to table: {op.table_name}")
            for sub_op in op.ops:
                lines.extend(self._op_to_sql(sub_op))

        else:
            lines.append(f"-- Unsupported operation: {type(op).__name__}")

        return lines
