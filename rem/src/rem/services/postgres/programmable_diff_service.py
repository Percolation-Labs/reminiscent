"""
Programmable object diff service for comparing functions, triggers, and views.

The schema diff service (Alembic-based) only compares tables/columns/indexes.
This service fills the gap by comparing programmable objects.

Problem solved:
- Functions/triggers/views defined with CREATE OR REPLACE in migration files
- Once migration is marked "applied", object changes aren't detected
- Database can drift from source SQL files

Solution:
- Extract object definitions from SQL files (source of truth)
- Compare against installed objects in database
- Generate sync SQL to update stale objects
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import asyncpg
from loguru import logger

from ...settings import settings


class ObjectType(str, Enum):
    FUNCTION = "function"
    TRIGGER = "trigger"
    VIEW = "view"


@dataclass
class ObjectDiff:
    """Difference detected for a single database object."""

    name: str
    object_type: ObjectType
    status: str  # "missing", "different", "extra"
    source_def: Optional[str] = None
    db_def: Optional[str] = None
    # For triggers, track the table they're on
    table_name: Optional[str] = None


@dataclass
class DiffResult:
    """Result of object comparison."""

    has_changes: bool
    diffs: list[ObjectDiff] = field(default_factory=list)
    sync_sql: str = ""

    @property
    def missing_count(self) -> int:
        return sum(1 for d in self.diffs if d.status == "missing")

    @property
    def different_count(self) -> int:
        return sum(1 for d in self.diffs if d.status == "different")

    @property
    def extra_count(self) -> int:
        return sum(1 for d in self.diffs if d.status == "extra")

    def by_type(self, obj_type: ObjectType) -> list[ObjectDiff]:
        """Get diffs filtered by object type."""
        return [d for d in self.diffs if d.object_type == obj_type]

    def summary(self) -> str:
        """Human-readable summary of differences."""
        lines = []
        for obj_type in ObjectType:
            type_diffs = self.by_type(obj_type)
            if type_diffs:
                missing = sum(1 for d in type_diffs if d.status == "missing")
                different = sum(1 for d in type_diffs if d.status == "different")
                extra = sum(1 for d in type_diffs if d.status == "extra")
                parts = []
                if missing:
                    parts.append(f"{missing} missing")
                if different:
                    parts.append(f"{different} different")
                if extra:
                    parts.append(f"{extra} extra")
                lines.append(f"  {obj_type.value}s: {', '.join(parts)}")
        return "\n".join(lines) if lines else "  No differences found"


class ProgrammableDiffService:
    """
    Service for comparing SQL functions, triggers, and views between source files and database.

    Usage:
        service = ProgrammableDiffService()
        result = await service.compute_diff()

        if result.has_changes:
            print(result.sync_sql)  # SQL to sync objects
    """

    def __init__(self, sql_dir: Optional[Path] = None):
        """
        Initialize diff service.

        Args:
            sql_dir: Directory containing SQL files with object definitions.
                    Defaults to rem/sql/migrations/
        """
        if sql_dir is None:
            import rem

            sql_dir = Path(rem.__file__).parent / "sql" / "migrations"

        self.sql_dir = sql_dir

    # =========================================================================
    # FUNCTION EXTRACTION AND COMPARISON
    # =========================================================================

    def _extract_functions_from_sql(self, sql_content: str) -> dict[str, str]:
        """
        Extract function definitions from SQL content.

        Returns:
            Dict mapping function name -> full CREATE OR REPLACE FUNCTION statement
        """
        functions = {}

        # Pattern to match CREATE OR REPLACE FUNCTION ... $$ ... $$ LANGUAGE ...
        # Handles both $function$ and $$ delimiters
        # Captures through LANGUAGE clause and optional modifiers (STABLE, IMMUTABLE, etc.)
        pattern = r"""
            (CREATE\s+OR\s+REPLACE\s+FUNCTION\s+
            (?:public\.)?(\w+)\s*\([^)]*\)  # function name and params
            .*?                              # return type etc
            AS\s+\$(\w*)\$                   # opening delimiter
            .*?                              # function body
            \$\3\$                            # matching closing delimiter
            \s*LANGUAGE\s+\w+                 # LANGUAGE clause (required)
            (?:\s+(?:STABLE|IMMUTABLE|VOLATILE|SECURITY\s+DEFINER|SECURITY\s+INVOKER))* # optional modifiers
            )
        """

        for match in re.finditer(pattern, sql_content, re.DOTALL | re.IGNORECASE | re.VERBOSE):
            full_def = match.group(1).strip()
            func_name = match.group(2).lower()
            functions[func_name] = full_def

        return functions

    async def get_db_functions(self, conn: asyncpg.Connection) -> dict[str, str]:
        """Get all function definitions from the database."""
        rows = await conn.fetch("""
            SELECT
                proname as name,
                pg_get_functiondef(oid) as definition
            FROM pg_proc
            WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            AND prokind = 'f'
        """)

        return {row["name"]: row["definition"] for row in rows}

    def _normalize_function_def(self, func_def: str) -> str:
        """Normalize function definition for comparison."""
        # Remove comments
        func_def = re.sub(r"--.*$", "", func_def, flags=re.MULTILINE)

        # Normalize whitespace
        func_def = re.sub(r"\s+", " ", func_def).strip()

        # Normalize case for keywords
        keywords = [
            "CREATE", "OR", "REPLACE", "FUNCTION", "RETURNS", "LANGUAGE",
            "AS", "BEGIN", "END", "IF", "THEN", "ELSE", "ELSIF", "RETURN",
            "DECLARE", "SELECT", "INSERT", "UPDATE", "DELETE", "FROM",
            "WHERE", "INTO", "VALUES", "ON", "CONFLICT", "DO", "SET",
            "NULL", "NOT", "AND", "TRUE", "FALSE", "COALESCE", "EXISTS",
            "TRIGGER", "FOR", "EACH", "ROW", "EXECUTE", "PROCEDURE",
            "IMMUTABLE", "STABLE", "VOLATILE", "PLPGSQL", "SQL",
        ]
        for kw in keywords:
            func_def = re.sub(rf"\b{kw}\b", kw, func_def, flags=re.IGNORECASE)

        return func_def

    def _functions_match(self, source_def: str, db_def: str) -> bool:
        """Compare two function definitions for equivalence."""
        norm_source = self._normalize_function_def(source_def)
        norm_db = self._normalize_function_def(db_def)

        def extract_body(text: str) -> str:
            match = re.search(r"\$\w*\$(.*)\$\w*\$", text, re.DOTALL)
            if match:
                return self._normalize_function_def(match.group(1))
            return text

        return extract_body(norm_source) == extract_body(norm_db)

    # =========================================================================
    # TRIGGER EXTRACTION AND COMPARISON
    # =========================================================================

    def _extract_triggers_from_sql(self, sql_content: str) -> dict[str, tuple[str, str]]:
        """
        Extract trigger definitions from SQL content.

        Returns:
            Dict mapping trigger name -> (full CREATE TRIGGER statement, table_name)
        """
        triggers = {}

        # Pattern for CREATE TRIGGER (with optional OR REPLACE for pg14+)
        # CREATE [OR REPLACE] TRIGGER name {BEFORE|AFTER|INSTEAD OF} event ON table ...
        pattern = r"""
            (CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+
            (\w+)\s+                              # trigger name
            (?:BEFORE|AFTER|INSTEAD\s+OF)\s+     # timing
            (?:INSERT|UPDATE|DELETE|TRUNCATE)    # first event
            (?:\s+OR\s+(?:INSERT|UPDATE|DELETE|TRUNCATE))*  # additional events
            \s+ON\s+
            (?:public\.)?(\w+)                   # table name
            .*?                                   # rest of definition
            EXECUTE\s+(?:FUNCTION|PROCEDURE)\s+
            (?:public\.)?(\w+)\s*\([^)]*\)       # function name
            )
        """

        for match in re.finditer(pattern, sql_content, re.DOTALL | re.IGNORECASE | re.VERBOSE):
            full_def = match.group(1).strip()
            trigger_name = match.group(2).lower()
            table_name = match.group(3).lower()
            triggers[trigger_name] = (full_def, table_name)

        return triggers

    async def get_db_triggers(self, conn: asyncpg.Connection) -> dict[str, tuple[str, str]]:
        """
        Get all trigger definitions from the database.

        Returns:
            Dict mapping trigger name -> (definition, table_name)
        """
        rows = await conn.fetch("""
            SELECT
                t.tgname as name,
                pg_get_triggerdef(t.oid) as definition,
                c.relname as table_name
            FROM pg_trigger t
            JOIN pg_class c ON t.tgrelid = c.oid
            WHERE c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            AND NOT t.tgisinternal
        """)

        return {row["name"]: (row["definition"], row["table_name"]) for row in rows}

    def _normalize_trigger_def(self, trigger_def: str) -> str:
        """Normalize trigger definition for comparison."""
        # Remove comments
        trigger_def = re.sub(r"--.*$", "", trigger_def, flags=re.MULTILINE)

        # Normalize whitespace
        trigger_def = re.sub(r"\s+", " ", trigger_def).strip()

        # Normalize case for keywords
        keywords = [
            "CREATE", "OR", "REPLACE", "TRIGGER", "BEFORE", "AFTER",
            "INSTEAD", "OF", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
            "ON", "FOR", "EACH", "ROW", "STATEMENT", "EXECUTE",
            "FUNCTION", "PROCEDURE", "WHEN", "NEW", "OLD", "AND", "OR",
        ]
        for kw in keywords:
            trigger_def = re.sub(rf"\b{kw}\b", kw, trigger_def, flags=re.IGNORECASE)

        return trigger_def

    def _triggers_match(self, source_def: str, db_def: str) -> bool:
        """Compare two trigger definitions for equivalence."""
        norm_source = self._normalize_trigger_def(source_def)
        norm_db = self._normalize_trigger_def(db_def)

        # pg_get_triggerdef() output differs from source slightly
        # Extract key components for comparison
        def extract_key_parts(text: str) -> tuple:
            # Extract: timing, events, table, for each, function
            timing = re.search(r"\b(BEFORE|AFTER|INSTEAD OF)\b", text, re.IGNORECASE)
            events = re.findall(r"\b(INSERT|UPDATE|DELETE|TRUNCATE)\b", text, re.IGNORECASE)
            table = re.search(r"\bON\s+(?:public\.)?(\w+)", text, re.IGNORECASE)
            for_each = re.search(r"\bFOR\s+EACH\s+(ROW|STATEMENT)\b", text, re.IGNORECASE)
            func = re.search(r"\bEXECUTE\s+(?:FUNCTION|PROCEDURE)\s+(?:public\.)?(\w+)", text, re.IGNORECASE)

            return (
                timing.group(1).upper() if timing else "",
                sorted(set(e.upper() for e in events)),
                table.group(1).lower() if table else "",
                for_each.group(1).upper() if for_each else "STATEMENT",
                func.group(1).lower() if func else "",
            )

        return extract_key_parts(norm_source) == extract_key_parts(norm_db)

    # =========================================================================
    # VIEW EXTRACTION AND COMPARISON
    # =========================================================================

    def _extract_views_from_sql(self, sql_content: str) -> dict[str, str]:
        """
        Extract view definitions from SQL content.

        Returns:
            Dict mapping view name -> full CREATE VIEW statement
        """
        views = {}

        # Pattern for CREATE [OR REPLACE] VIEW name AS SELECT ...
        # Views end at semicolon
        pattern = r"""
            (CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+
            (?:public\.)?(\w+)\s+                # view name
            AS\s+
            SELECT\s+.*?)                        # SELECT query
            ;                                    # terminated by semicolon
        """

        for match in re.finditer(pattern, sql_content, re.DOTALL | re.IGNORECASE | re.VERBOSE):
            full_def = match.group(1).strip()
            view_name = match.group(2).lower()
            views[view_name] = full_def

        return views

    async def get_db_views(self, conn: asyncpg.Connection) -> dict[str, str]:
        """Get all view definitions from the database."""
        rows = await conn.fetch("""
            SELECT
                viewname as name,
                'CREATE OR REPLACE VIEW ' || viewname || ' AS ' || definition as definition
            FROM pg_views
            WHERE schemaname = 'public'
        """)

        return {row["name"]: row["definition"] for row in rows}

    def _normalize_view_def(self, view_def: str) -> str:
        """Normalize view definition for comparison."""
        # Remove comments
        view_def = re.sub(r"--.*$", "", view_def, flags=re.MULTILINE)

        # Normalize whitespace
        view_def = re.sub(r"\s+", " ", view_def).strip()

        # Normalize case for keywords
        keywords = [
            "CREATE", "OR", "REPLACE", "VIEW", "AS", "SELECT", "FROM",
            "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL",
            "ON", "AND", "OR", "NOT", "IN", "EXISTS", "BETWEEN", "LIKE",
            "IS", "NULL", "TRUE", "FALSE", "CASE", "WHEN", "THEN", "ELSE",
            "END", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET",
            "UNION", "INTERSECT", "EXCEPT", "ALL", "DISTINCT", "AS",
            "COALESCE", "NULLIF", "CAST", "EXTRACT", "COUNT", "SUM",
            "AVG", "MIN", "MAX", "WITH",
        ]
        for kw in keywords:
            view_def = re.sub(rf"\b{kw}\b", kw, view_def, flags=re.IGNORECASE)

        return view_def

    def _views_match(self, source_def: str, db_def: str) -> bool:
        """Compare two view definitions for equivalence."""
        norm_source = self._normalize_view_def(source_def)
        norm_db = self._normalize_view_def(db_def)

        # Extract just the SELECT query for comparison
        def extract_select(text: str) -> str:
            match = re.search(r"\bAS\s+(SELECT\s+.*)", text, re.IGNORECASE | re.DOTALL)
            if match:
                return self._normalize_view_def(match.group(1))
            return text

        return extract_select(norm_source) == extract_select(norm_db)

    # =========================================================================
    # UNIFIED SOURCE EXTRACTION
    # =========================================================================

    def get_source_objects(self) -> tuple[dict[str, str], dict[str, tuple[str, str]], dict[str, str]]:
        """
        Extract all object definitions from SQL migration files.

        Returns:
            Tuple of (functions, triggers, views) dicts
        """
        all_functions = {}
        all_triggers = {}
        all_views = {}

        if not self.sql_dir.exists():
            logger.warning(f"SQL directory not found: {self.sql_dir}")
            return all_functions, all_triggers, all_views

        # Process migration files in order (later definitions override earlier)
        for sql_file in sorted(self.sql_dir.glob("*.sql")):
            content = sql_file.read_text()

            functions = self._extract_functions_from_sql(content)
            triggers = self._extract_triggers_from_sql(content)
            views = self._extract_views_from_sql(content)

            all_functions.update(functions)
            all_triggers.update(triggers)
            all_views.update(views)

            if functions or triggers or views:
                logger.debug(
                    f"{sql_file.name}: {len(functions)} functions, "
                    f"{len(triggers)} triggers, {len(views)} views"
                )

        return all_functions, all_triggers, all_views

    # =========================================================================
    # DIFF COMPUTATION
    # =========================================================================

    async def compute_diff(
        self,
        connection_string: Optional[str] = None,
        include_extra: bool = False,
        object_types: Optional[list[ObjectType]] = None,
    ) -> DiffResult:
        """
        Compare objects between SQL files and database.

        Args:
            connection_string: PostgreSQL connection string (uses settings if not provided)
            include_extra: If True, report objects in DB but not in source
            object_types: Which object types to check (default: all)

        Returns:
            DiffResult with detected differences
        """
        if object_types is None:
            object_types = list(ObjectType)

        conn_str = connection_string or settings.postgres.connection_string

        # Get source objects
        source_functions, source_triggers, source_views = self.get_source_objects()
        logger.info(
            f"Source: {len(source_functions)} functions, "
            f"{len(source_triggers)} triggers, {len(source_views)} views"
        )

        # Get database objects
        conn = await asyncpg.connect(conn_str)
        try:
            db_functions = await self.get_db_functions(conn) if ObjectType.FUNCTION in object_types else {}
            db_triggers = await self.get_db_triggers(conn) if ObjectType.TRIGGER in object_types else {}
            db_views = await self.get_db_views(conn) if ObjectType.VIEW in object_types else {}
            logger.info(
                f"Database: {len(db_functions)} functions, "
                f"{len(db_triggers)} triggers, {len(db_views)} views"
            )
        finally:
            await conn.close()

        diffs = []
        sync_sql_parts = []

        # Compare functions
        if ObjectType.FUNCTION in object_types:
            for name, source_def in source_functions.items():
                if name not in db_functions:
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.FUNCTION,
                        status="missing",
                        source_def=source_def,
                    ))
                    sync_sql_parts.append(f"-- Missing function: {name}")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")
                elif not self._functions_match(source_def, db_functions[name]):
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.FUNCTION,
                        status="different",
                        source_def=source_def,
                        db_def=db_functions[name],
                    ))
                    sync_sql_parts.append(f"-- Different function: {name}")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")

            if include_extra:
                for name in db_functions:
                    if name not in source_functions:
                        diffs.append(ObjectDiff(
                            name=name,
                            object_type=ObjectType.FUNCTION,
                            status="extra",
                            db_def=db_functions[name],
                        ))

        # Compare triggers
        if ObjectType.TRIGGER in object_types:
            for name, (source_def, table_name) in source_triggers.items():
                if name not in db_triggers:
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.TRIGGER,
                        status="missing",
                        source_def=source_def,
                        table_name=table_name,
                    ))
                    # Drop trigger first if exists (for CREATE without OR REPLACE)
                    sync_sql_parts.append(f"-- Missing trigger: {name}")
                    sync_sql_parts.append(f"DROP TRIGGER IF EXISTS {name} ON {table_name};")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")
                elif not self._triggers_match(source_def, db_triggers[name][0]):
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.TRIGGER,
                        status="different",
                        source_def=source_def,
                        db_def=db_triggers[name][0],
                        table_name=table_name,
                    ))
                    sync_sql_parts.append(f"-- Different trigger: {name}")
                    sync_sql_parts.append(f"DROP TRIGGER IF EXISTS {name} ON {table_name};")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")

            if include_extra:
                for name in db_triggers:
                    if name not in source_triggers:
                        diffs.append(ObjectDiff(
                            name=name,
                            object_type=ObjectType.TRIGGER,
                            status="extra",
                            db_def=db_triggers[name][0],
                            table_name=db_triggers[name][1],
                        ))

        # Compare views
        if ObjectType.VIEW in object_types:
            for name, source_def in source_views.items():
                if name not in db_views:
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.VIEW,
                        status="missing",
                        source_def=source_def,
                    ))
                    sync_sql_parts.append(f"-- Missing view: {name}")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")
                elif not self._views_match(source_def, db_views[name]):
                    diffs.append(ObjectDiff(
                        name=name,
                        object_type=ObjectType.VIEW,
                        status="different",
                        source_def=source_def,
                        db_def=db_views[name],
                    ))
                    sync_sql_parts.append(f"-- Different view: {name}")
                    sync_sql_parts.append(source_def + ";")
                    sync_sql_parts.append("")

            if include_extra:
                for name in db_views:
                    if name not in source_views:
                        diffs.append(ObjectDiff(
                            name=name,
                            object_type=ObjectType.VIEW,
                            status="extra",
                            db_def=db_views[name],
                        ))

        has_changes = len([d for d in diffs if d.status in ("missing", "different")]) > 0

        return DiffResult(
            has_changes=has_changes,
            diffs=diffs,
            sync_sql="\n".join(sync_sql_parts) if sync_sql_parts else "",
        )

    async def sync(
        self,
        connection_string: Optional[str] = None,
        dry_run: bool = True,
        object_types: Optional[list[ObjectType]] = None,
    ) -> DiffResult:
        """
        Sync objects from SQL files to database.

        Args:
            connection_string: PostgreSQL connection string
            dry_run: If True, only report what would change (don't apply)
            object_types: Which object types to sync (default: all)

        Returns:
            DiffResult with applied changes
        """
        result = await self.compute_diff(connection_string, object_types=object_types)

        if not result.has_changes:
            logger.info("All programmable objects are in sync")
            return result

        if dry_run:
            logger.info(f"Dry run - changes needed:\n{result.summary()}")
            return result

        # Apply sync SQL
        conn_str = connection_string or settings.postgres.connection_string
        conn = await asyncpg.connect(conn_str)
        try:
            await conn.execute(result.sync_sql)
            logger.info(f"Applied changes:\n{result.summary()}")
        finally:
            await conn.close()

        return result


# Backwards compatibility alias
FunctionDiffService = ProgrammableDiffService
FunctionDiff = ObjectDiff
FunctionDiffResult = DiffResult
