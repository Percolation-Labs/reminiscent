"""
Migration service for managing Alembic-based database migrations.

This service provides:
1. SQL diff generation between target database and Pydantic models
2. Migration planning (dry-run)
3. Migration application
4. SQL file execution
5. Safety validation for migration operations
"""

import io
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from loguru import logger

from ...settings import settings


@dataclass
class MigrationSafetyResult:
    """Result of migration safety validation."""

    is_safe: bool
    errors: list[str]
    warnings: list[str]
    sql: str


class MigrationService:
    """
    Service for managing database migrations using Alembic.

    Integrates Alembic with REM's Pydantic model-first approach.
    """

    def __init__(self, alembic_cfg_path: Optional[Path] = None):
        """
        Initialize migration service.

        Args:
            alembic_cfg_path: Path to alembic.ini (defaults to package alembic.ini)
        """
        if alembic_cfg_path is None:
            # Find alembic.ini in package root
            import rem

            package_root = Path(rem.__file__).parent.parent.parent
            alembic_cfg_path = package_root / "alembic.ini"

        if not alembic_cfg_path.exists():
            raise FileNotFoundError(f"Alembic config not found: {alembic_cfg_path}")

        self.alembic_cfg = Config(str(alembic_cfg_path))
        self.alembic_cfg.set_main_option(
            "script_location", str(alembic_cfg_path.parent / "alembic")
        )

    def get_connection_string(self, target_db: Optional[str] = None) -> str:
        """
        Build PostgreSQL connection string.

        Args:
            target_db: Override database name (useful for comparing against different DB)

        Returns:
            PostgreSQL connection string
        """
        pg = settings.postgres

        url = f"postgresql://{pg.user}"
        if pg.password:
            url += f":{pg.password}"

        db_name = target_db or pg.database
        url += f"@{pg.host}:{pg.port}/{db_name}"

        return url

    def generate_migration_sql(
        self,
        output_file: Optional[Path] = None,
        target_db: Optional[str] = None,
        message: str = "Auto-generated migration",
    ) -> str:
        """
        Generate SQL diff between current models and target database using Alembic autogenerate.

        This uses Alembic's autogenerate feature to compare the Pydantic models
        (via SQLAlchemy metadata) with the target database schema.

        Args:
            output_file: Path to write SQL file (if None, returns SQL string)
            target_db: Target database name (overrides settings)
            message: Migration message/description

        Returns:
            Generated SQL as string
        """
        # Override database URL if target_db provided
        url = self.get_connection_string(target_db)
        self.alembic_cfg.set_main_option("sqlalchemy.url", url)

        # Generate migration SQL using autogenerate
        # We'll use upgrade --sql to generate SQL without applying
        stdout_buffer = io.StringIO()

        try:
            # First, create an autogenerate revision to detect changes
            with redirect_stdout(stdout_buffer):
                command.revision(
                    self.alembic_cfg,
                    message=message,
                    autogenerate=True,
                )

            # Get the revision that was just created
            script_dir = ScriptDirectory.from_config(self.alembic_cfg)
            revision = script_dir.get_current_head()

            if revision is None:
                logger.warning("No changes detected - models match database")
                return "-- No changes detected"

            # Now generate SQL from that revision
            sql_buffer = io.StringIO()
            with redirect_stdout(sql_buffer):
                command.upgrade(
                    self.alembic_cfg,
                    f"{revision}:head",
                    sql=True,
                )

            sql = sql_buffer.getvalue()

            # If no SQL was generated, check the revision file
            if not sql.strip() or "-- Running upgrade" not in sql:
                # Read the revision file directly
                version_path = script_dir.get_revision(revision).path
                sql = f"-- Generated from Alembic revision: {revision}\n"
                sql += f"-- Migration file: {version_path}\n"
                sql += "-- Run: alembic upgrade head\n"
                sql += "-- Or use this migration file to review/edit before applying\n\n"

                # Try to extract upgrade operations from the revision file
                if version_path:
                    with open(version_path, "r") as f:
                        content = f.read()
                        # Extract the upgrade function
                        import re

                        upgrade_match = re.search(
                            r"def upgrade\(\).*?:\s*(.*?)(?=def downgrade|$)",
                            content,
                            re.DOTALL,
                        )
                        if upgrade_match:
                            upgrade_code = upgrade_match.group(1).strip()
                            if upgrade_code and upgrade_code != "pass":
                                sql += f"-- Upgrade operations:\n{upgrade_code}\n"

            # Write to output file if specified
            if output_file and sql.strip():
                output_file.write_text(sql)
                logger.info(f"Migration SQL written to {output_file}")

            return sql if sql.strip() else "-- No changes detected"

        except Exception as e:
            logger.error(f"Failed to generate migration: {e}")
            return f"-- Error generating migration: {e}"

    def plan_migration(self, target_db: Optional[str] = None) -> str:
        """
        Plan a migration (dry-run) showing what would change.

        Args:
            target_db: Target database to compare against

        Returns:
            Human-readable migration plan
        """
        sql = self.generate_migration_sql(target_db=target_db)

        if "No changes detected" in sql:
            return "No changes detected between models and database."

        return f"Migration Plan:\n\n{sql}"

    def apply_sql_file(
        self, sql_file: Path, connection_string: Optional[str] = None
    ) -> bool:
        """
        Apply a SQL file to the database using psql.

        Args:
            sql_file: Path to SQL file
            connection_string: PostgreSQL connection string (uses settings if not provided)

        Returns:
            True if successful, False otherwise
        """
        if not sql_file.exists():
            raise FileNotFoundError(f"SQL file not found: {sql_file}")

        conn_str = connection_string or self.get_connection_string()

        try:
            result = subprocess.run(
                ["psql", conn_str, "-f", str(sql_file), "-v", "ON_ERROR_STOP=1"],
                capture_output=True,
                text=True,
                check=True,
            )

            logger.info(f"Successfully applied {sql_file}")
            if result.stdout:
                logger.debug(result.stdout)

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to apply {sql_file}: {e.stderr or e.stdout}")
            return False

        except FileNotFoundError:
            logger.error(
                "psql command not found. Ensure PostgreSQL client is installed."
            )
            return False

    def apply_migration(self, target_db: Optional[str] = None) -> bool:
        """
        Generate and apply migration in one step.

        Args:
            target_db: Target database to migrate

        Returns:
            True if successful, False otherwise
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False
        ) as f:
            sql_file = Path(f.name)

        try:
            sql = self.generate_migration_sql(output_file=sql_file, target_db=target_db)

            if "No changes detected" in sql:
                logger.info("No migration needed")
                return True

            return self.apply_sql_file(sql_file)

        finally:
            # Clean up temp file
            if sql_file.exists():
                sql_file.unlink()

    def get_current_revision(self) -> Optional[str]:
        """
        Get current database revision.

        Returns:
            Current revision ID or None if no migrations applied
        """
        try:
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                command.current(self.alembic_cfg)
            output = stdout_buffer.getvalue()
            # Parse the output to get revision ID
            import re

            match = re.search(r"([a-f0-9]+)\s+\(head\)", output)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            logger.error(f"Could not get current revision: {e}")
            return None

    def validate_migration_safety(
        self, sql: str, safe_mode: Optional[str] = None
    ) -> MigrationSafetyResult:
        """
        Validate migration SQL against safety rules.

        Args:
            sql: Migration SQL to validate
            safe_mode: Override safety mode (uses settings if not provided)

        Returns:
            MigrationSafetyResult with validation results
        """
        mode = safe_mode or settings.migration.mode
        errors: list[str] = []
        warnings: list[str] = []

        # Normalize SQL for pattern matching
        sql_upper = sql.upper()

        # Check for DROP COLUMN
        if re.search(r"\bDROP\s+COLUMN\b", sql_upper, re.IGNORECASE):
            if mode in ("additive", "strict"):
                errors.append("DROP COLUMN not allowed in safe mode")
            elif not settings.migration.allow_drop_columns:
                errors.append(
                    "DROP COLUMN not allowed (MIGRATION__ALLOW_DROP_COLUMNS=false)"
                )
            elif settings.migration.unsafe_alter_warning:
                warnings.append("Migration contains DROP COLUMN operations")

        # Check for DROP TABLE
        if re.search(r"\bDROP\s+TABLE\b", sql_upper, re.IGNORECASE):
            if mode in ("additive", "strict"):
                errors.append("DROP TABLE not allowed in safe mode")
            elif not settings.migration.allow_drop_tables:
                errors.append(
                    "DROP TABLE not allowed (MIGRATION__ALLOW_DROP_TABLES=false)"
                )
            elif settings.migration.unsafe_alter_warning:
                warnings.append("Migration contains DROP TABLE operations")

        # Check for ALTER COLUMN (type changes)
        if re.search(r"\bALTER\s+COLUMN\s+\w+\s+TYPE\b", sql_upper, re.IGNORECASE):
            if mode == "strict":
                errors.append("ALTER COLUMN TYPE not allowed in strict mode")
            elif not settings.migration.allow_alter_columns:
                errors.append(
                    "ALTER COLUMN TYPE not allowed (MIGRATION__ALLOW_ALTER_COLUMNS=false)"
                )
            elif settings.migration.unsafe_alter_warning:
                warnings.append("Migration contains ALTER COLUMN TYPE operations")

        # Check for RENAME COLUMN
        if re.search(r"\bRENAME\s+COLUMN\b", sql_upper, re.IGNORECASE):
            if mode == "strict":
                errors.append("RENAME COLUMN not allowed in strict mode")
            elif not settings.migration.allow_rename_columns:
                errors.append(
                    "RENAME COLUMN not allowed (MIGRATION__ALLOW_RENAME_COLUMNS=false)"
                )
            elif settings.migration.unsafe_alter_warning:
                warnings.append("Migration contains RENAME COLUMN operations")

        # Check for RENAME TABLE / ALTER TABLE RENAME
        if re.search(
            r"\b(RENAME\s+TABLE|ALTER\s+TABLE\s+\w+\s+RENAME\s+TO)\b",
            sql_upper,
            re.IGNORECASE,
        ):
            if mode == "strict":
                errors.append("RENAME TABLE not allowed in strict mode")
            elif not settings.migration.allow_rename_tables:
                errors.append(
                    "RENAME TABLE not allowed (MIGRATION__ALLOW_RENAME_TABLES=false)"
                )
            elif settings.migration.unsafe_alter_warning:
                warnings.append("Migration contains RENAME TABLE operations")

        # Check for other ALTER operations
        if (
            re.search(r"\bALTER\s+TABLE\b", sql_upper, re.IGNORECASE)
            and settings.migration.unsafe_alter_warning
        ):
            # Only warn if not already warned above
            if not any("ALTER" in w for w in warnings):
                warnings.append("Migration contains ALTER TABLE operations")

        is_safe = len(errors) == 0

        return MigrationSafetyResult(
            is_safe=is_safe,
            errors=errors,
            warnings=warnings,
            sql=sql,
        )

    def generate_migration_sql_safe(
        self,
        output_file: Optional[Path] = None,
        target_db: Optional[str] = None,
        message: str = "Auto-generated migration",
        safe_mode: Optional[str] = None,
    ) -> MigrationSafetyResult:
        """
        Generate migration SQL with safety validation.

        Args:
            output_file: Path to write SQL file (if None, returns SQL string)
            target_db: Target database name (overrides settings)
            message: Migration message/description
            safe_mode: Override safety mode (permissive, additive, strict)

        Returns:
            MigrationSafetyResult with validation results
        """
        # Generate SQL
        sql = self.generate_migration_sql(
            output_file=None,  # Don't write yet, validate first
            target_db=target_db,
            message=message,
        )

        # Validate safety
        result = self.validate_migration_safety(sql, safe_mode=safe_mode)

        # Write to file only if safe and output_file provided
        if result.is_safe and output_file:
            output_file.write_text(sql)
            logger.info(f"Migration SQL written to {output_file}")
        elif not result.is_safe:
            logger.warning("Migration contains unsafe operations, not writing to file")

        return result
