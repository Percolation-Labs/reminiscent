"""
Schema generation utility from Pydantic models.

Generates complete database schemas from:
1. REM's core models (Resource, Moment, User, etc.)
2. Models registered via rem.register_model() or rem.register_models()
3. Models discovered from a directory scan

Output includes:
- Primary tables
- Embeddings tables
- KV_STORE triggers
- Indexes (foreground and background)
- Migrations
- Schema table entries (for agent-like table access)

Usage:
    from rem.services.postgres.schema_generator import SchemaGenerator

    # Generate from registry (includes core + registered models)
    generator = SchemaGenerator()
    schema = await generator.generate_from_registry()

    # Or generate from directory (legacy)
    schema = await generator.generate_from_directory("src/rem/models/entities")

    # Write to file
    with open("src/rem/sql/schema.sql", "w") as f:
        f.write(schema)
"""

import importlib.util
import inspect
import json
import uuid
from pathlib import Path
from typing import Any, Type

from loguru import logger
from pydantic import BaseModel

from ...settings import settings
from ...utils.sql_paths import get_package_sql_dir
from .register_type import register_type, should_embed_field

# Namespace UUID for generating deterministic UUIDs from model names
# Using UUID5 with this namespace ensures same model always gets same UUID
REM_SCHEMA_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace


def generate_model_uuid(fully_qualified_name: str) -> uuid.UUID:
    """
    Generate deterministic UUID from fully qualified model name.

    Uses UUID5 (SHA-1 hash) with REM namespace for reproducibility.
    Same fully qualified name always produces same UUID.

    Args:
        fully_qualified_name: Full module path, e.g., "rem.models.entities.Resource"

    Returns:
        Deterministic UUID for this model
    """
    return uuid.uuid5(REM_SCHEMA_NAMESPACE, fully_qualified_name)


def extract_model_schema_metadata(
    model: Type[BaseModel],
    table_name: str,
    entity_key_field: str,
    include_search_tool: bool = True,
) -> dict[str, Any]:
    """
    Extract schema metadata from a Pydantic model for schemas table.

    Args:
        model: Pydantic model class
        table_name: Database table name
        entity_key_field: Field used as entity key in kv_store
        include_search_tool: If True, add search_rem tool for querying this table

    Returns:
        Dict with schema metadata ready for schemas table insert
    """
    # Get fully qualified name
    fqn = f"{model.__module__}.{model.__name__}"

    # Generate deterministic UUID
    schema_id = generate_model_uuid(fqn)

    # Get JSON schema from Pydantic
    json_schema = model.model_json_schema()

    # Find embedding fields
    embedding_fields = []
    for field_name, field_info in model.model_fields.items():
        if should_embed_field(field_name, field_info):
            embedding_fields.append(field_name)

    # Build description with search capability note
    base_description = model.__doc__ or f"Schema for {model.__name__}"
    search_note = (
        f"\n\nThis agent can search the `{table_name}` table using the `search_rem` tool. "
        f"Use REM query syntax: LOOKUP for exact match, FUZZY for typo-tolerant search, "
        f"SEARCH for semantic similarity, or SQL for complex queries."
    ) if include_search_tool else ""

    # Build spec with table metadata and tools
    # Note: default_search_table is used by create_agent to append a description
    # suffix to the search_rem tool when loading it dynamically
    has_embeddings = bool(embedding_fields)

    spec = {
        "type": "object",
        "description": base_description + search_note,
        "properties": json_schema.get("properties", {}),
        "required": json_schema.get("required", []),
        "json_schema_extra": {
            "table_name": table_name,
            "entity_key_field": entity_key_field,
            "embedding_fields": embedding_fields,
            "fully_qualified_name": fqn,
            "tools": ["search_rem"] if include_search_tool else [],
            "default_search_table": table_name,
            "has_embeddings": has_embeddings,
        },
    }

    # Build content (documentation)
    content = f"""# {model.__name__}

{base_description}

## Overview

The `{model.__name__}` entity is stored in the `{table_name}` table. Each record is uniquely
identified by its `{entity_key_field}` field for lookups and graph traversal.

## Search Capabilities

This schema includes the `search_rem` tool which supports:
- **LOOKUP**: O(1) exact match by {entity_key_field} (e.g., `LOOKUP "entity-name"`)
- **FUZZY**: Typo-tolerant search (e.g., `FUZZY "partial" THRESHOLD 0.3`)
- **SEARCH**: Semantic vector search on {', '.join(embedding_fields) if embedding_fields else 'content'} (e.g., `SEARCH "concept" FROM {table_name} LIMIT 10`)
- **SQL**: Complex queries (e.g., `SELECT * FROM {table_name} WHERE ...`)

## Table Info

| Property | Value |
|----------|-------|
| Table | `{table_name}` |
| Entity Key | `{entity_key_field}` |
| Embedding Fields | {', '.join(f'`{f}`' for f in embedding_fields) if embedding_fields else 'None'} |
| Tools | {', '.join(['`search_rem`'] if include_search_tool else ['None'])} |

## Fields

"""
    for field_name, field_info in model.model_fields.items():
        field_type = str(field_info.annotation) if field_info.annotation else "Any"
        field_desc = field_info.description or ""
        required = "Required" if field_info.is_required() else "Optional"
        content += f"### `{field_name}`\n"
        content += f"- **Type**: `{field_type}`\n"
        content += f"- **{required}**\n"
        if field_desc:
            content += f"- {field_desc}\n"
        content += "\n"

    return {
        "id": str(schema_id),
        "name": model.__name__,
        "table_name": table_name,
        "entity_key_field": entity_key_field,
        "embedding_fields": embedding_fields,
        "fqn": fqn,
        "spec": spec,
        "content": content,
        "category": "entity",
    }


def generate_schema_upsert_sql(schema_metadata: dict[str, Any]) -> str:
    """
    Generate SQL UPSERT statement for schemas table.

    Uses ON CONFLICT DO UPDATE for idempotency.

    Args:
        schema_metadata: Dict from extract_model_schema_metadata()

    Returns:
        SQL INSERT ... ON CONFLICT statement
    """
    # Escape single quotes in content and spec
    content_escaped = schema_metadata["content"].replace("'", "''")
    spec_json = json.dumps(schema_metadata["spec"]).replace("'", "''")

    sql = f"""
-- Schema entry for {schema_metadata['name']} ({schema_metadata['table_name']})
INSERT INTO schemas (id, tenant_id, name, content, spec, category, metadata)
VALUES (
    '{schema_metadata['id']}'::uuid,
    'system',
    '{schema_metadata['name']}',
    '{content_escaped}',
    '{spec_json}'::jsonb,
    'entity',
    '{{"table_name": "{schema_metadata['table_name']}", "entity_key_field": "{schema_metadata['entity_key_field']}", "embedding_fields": {json.dumps(schema_metadata['embedding_fields'])}, "fqn": "{schema_metadata['fqn']}"}}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    content = EXCLUDED.content,
    spec = EXCLUDED.spec,
    category = EXCLUDED.category,
    metadata = EXCLUDED.metadata,
    updated_at = CURRENT_TIMESTAMP;
"""
    return sql.strip()


class SchemaGenerator:
    """
    Generate database schema from Pydantic models in a directory.

    Discovers all Pydantic models in Python files and generates:
    - CREATE TABLE statements
    - Embeddings tables
    - KV_STORE triggers
    - Indexes
    """

    def __init__(self, output_dir: Path | None = None):
        """
        Initialize schema generator.

        Args:
            output_dir: Optional directory for output files (defaults to package sql dir)
        """
        self.output_dir = output_dir or get_package_sql_dir()
        self.schemas: dict[str, dict] = {}

    def discover_models(self, directory: str | Path) -> dict[str, Type[BaseModel]]:
        """
        Discover all Pydantic models in a directory.

        Args:
            directory: Path to directory containing Python files with models

        Returns:
            Dict mapping model name to model class
        """
        import sys
        import importlib

        directory = Path(directory).resolve()
        models = {}

        logger.info(f"Discovering models in {directory}")

        # Add src directory to Python path to handle relative imports
        src_dir = directory
        while src_dir.name != "src" and src_dir.parent != src_dir:
            src_dir = src_dir.parent

        if src_dir.name == "src" and str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
            logger.debug(f"Added {src_dir} to sys.path for relative imports")

        # Convert directory path to module path
        # e.g., /path/to/src/rem/models/entities -> rem.models.entities
        try:
            rel_path = directory.relative_to(src_dir)
            module_path = str(rel_path).replace("/", ".")

            # Import the package to get all submodules
            package = importlib.import_module(module_path)

            # Find all Python files in the directory
            for py_file in directory.rglob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                try:
                    # Build module name from file path
                    rel_file = py_file.relative_to(src_dir)
                    module_name = str(rel_file.with_suffix("")).replace("/", ".")

                    # Import the module
                    module = importlib.import_module(module_name)

                    # Find Pydantic models
                    for name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and issubclass(obj, BaseModel)
                            and obj is not BaseModel
                            and not name.startswith("_")
                            # Only include models defined in this module
                            and obj.__module__ == module_name
                        ):
                            models[name] = obj
                            logger.debug(f"Found model: {name} in {module_name}")

                except Exception as e:
                    logger.warning(f"Failed to load {py_file}: {e}")

        except Exception as e:
            logger.error(f"Failed to discover models in {directory}: {e}")

        logger.info(f"Discovered {len(models)} models")
        return models

    def infer_table_name(self, model: Type[BaseModel]) -> str:
        """
        Infer table name from model class name.

        Converts CamelCase to snake_case and pluralizes.

        Examples:
            Resource -> resources
            UserProfile -> user_profiles
            Message -> messages

        Args:
            model: Pydantic model class

        Returns:
            Table name
        """
        import re

        name = model.__name__

        # Convert CamelCase to snake_case
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

        # Simple pluralization (add 's' if doesn't end in 's')
        if not name.endswith("s"):
            if name.endswith("y"):
                name = name[:-1] + "ies"  # category -> categories
            else:
                name = name + "s"  # resource -> resources

        return name

    def infer_entity_key_field(self, model: Type[BaseModel]) -> str:
        """
        Infer which field to use as entity_key in KV_STORE.

        Priority:
        1. Field with json_schema_extra={\"entity_key\": True}
        2. Field named \"name\" (human-readable identifier)
        3. Field named \"key\"
        4. Field named \"uri\"
        5. Field named \"id\" (fallback)

        Args:
            model: Pydantic model class

        Returns:
            Field name to use as entity_key
        """
        # Check for explicit entity_key marker
        for field_name, field_info in model.model_fields.items():
            json_extra = getattr(field_info, "json_schema_extra", None)
            if json_extra and isinstance(json_extra, dict):
                if json_extra.get("entity_key"):
                    return field_name

        # Check for key fields in priority order: name -> key -> uri -> id
        # (matching sql_builder.get_entity_key convention)
        for candidate in ["name", "key", "uri", "id"]:
            if candidate in model.model_fields:
                return candidate

        # Should never reach here for CoreModel subclasses (they all have id)
        logger.error(f"No suitable entity_key field found for {model.__name__}, using 'id'")
        return "id"

    async def generate_schema_for_model(
        self,
        model: Type[BaseModel],
        table_name: str | None = None,
        entity_key_field: str | None = None,
    ) -> dict:
        """
        Generate schema for a single model.

        Args:
            model: Pydantic model class
            table_name: Optional table name (inferred if not provided)
            entity_key_field: Optional entity key field (inferred if not provided)

        Returns:
            Dict with SQL statements and metadata
        """
        if table_name is None:
            table_name = self.infer_table_name(model)

        if entity_key_field is None:
            entity_key_field = self.infer_entity_key_field(model)

        logger.info(f"Generating schema for {model.__name__} -> {table_name}")

        schema = await register_type(
            model=model,
            table_name=table_name,
            entity_key_field=entity_key_field,
            tenant_scoped=True,
            create_embeddings=True,
            create_kv_trigger=True,
        )

        # Extract schema metadata for schemas table entry
        schema_metadata = extract_model_schema_metadata(
            model=model,
            table_name=table_name,
            entity_key_field=entity_key_field,
        )
        schema["schema_metadata"] = schema_metadata

        self.schemas[table_name] = schema
        return schema

    async def generate_from_registry(
        self, output_file: str | None = None, include_core: bool = True
    ) -> str:
        """
        Generate complete schema from the model registry.

        Includes:
        1. REM's core models (if include_core=True)
        2. Models registered via rem.register_model() or rem.register_models()

        Args:
            output_file: Optional output file path (relative to output_dir)
            include_core: If True, include REM's core models (default: True)

        Returns:
            Complete SQL schema as string

        Example:
            import rem
            from rem.models.core import CoreModel

            # Register custom model
            @rem.register_model
            class CustomEntity(CoreModel):
                name: str

            # Generate schema (includes core + custom)
            generator = SchemaGenerator()
            schema = await generator.generate_from_registry()
        """
        from ...registry import get_model_registry

        registry = get_model_registry()
        models = registry.get_models(include_core=include_core)

        logger.info(f"Generating schema from registry: {len(models)} models")

        # Generate schemas for each model
        for model_name, ext in models.items():
            await self.generate_schema_for_model(
                ext.model,
                table_name=ext.table_name,
                entity_key_field=ext.entity_key_field,
            )

        return self._generate_sql_output(
            source="model registry",
            output_file=output_file,
        )

    async def generate_from_directory(
        self, directory: str | Path, output_file: str | None = None
    ) -> str:
        """
        Generate complete schema from all models in a directory.

        Note: For most use cases, prefer generate_from_registry() which uses
        the model registry pattern.

        Args:
            directory: Path to directory with Pydantic models
            output_file: Optional output file path (relative to output_dir)

        Returns:
            Complete SQL schema as string
        """
        # Discover models
        models = self.discover_models(directory)

        # Generate schemas for each model
        for model_name, model in models.items():
            await self.generate_schema_for_model(model)

        return self._generate_sql_output(
            source=f"directory: {directory}",
            output_file=output_file,
        )

    def _generate_sql_output(
        self, source: str, output_file: str | None = None
    ) -> str:
        """
        Generate SQL output from accumulated schemas.

        Args:
            source: Description of schema source (for header comment)
            output_file: Optional output file path (relative to output_dir)

        Returns:
            Complete SQL schema as string
        """
        import datetime

        sql_parts = [
            "-- REM Model Schema (install_models.sql)",
            "-- Generated from Pydantic models",
            f"-- Source: {source}",
            f"-- Generated at: {datetime.datetime.now().isoformat()}",
            "--",
            "-- DO NOT EDIT MANUALLY - Regenerate with: rem db schema generate",
            "--",
            "-- This script creates:",
            "-- 1. Primary entity tables",
            "-- 2. Embeddings tables (embeddings_<table>)",
            "-- 3. KV_STORE triggers for cache maintenance",
            "-- 4. Indexes (foreground only, background indexes separate)",
            "-- 5. Schema table entries (for agent-like table access)",
            "",
            "-- ============================================================================",
            "-- PREREQUISITES CHECK",
            "-- ============================================================================",
            "",
            "DO $$",
            "BEGIN",
            "    -- Check that install.sql has been run",
            "    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'kv_store') THEN",
            "        RAISE EXCEPTION 'KV_STORE table not found. Run migrations/001_install.sql first.';",
            "    END IF;",
            "",
            "    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN",
            "        RAISE EXCEPTION 'pgvector extension not found. Run migrations/001_install.sql first.';",
            "    END IF;",
            "",
            "    RAISE NOTICE 'Prerequisites check passed';",
            "END $$;",
            "",
        ]

        # Add each table schema
        for table_name, schema in self.schemas.items():
            sql_parts.append("-- " + "=" * 70)
            sql_parts.append(f"-- {table_name.upper()} (Model: {schema['model']})")
            sql_parts.append("-- " + "=" * 70)
            sql_parts.append("")

            # Primary table
            if "table" in schema["sql"]:
                sql_parts.append(schema["sql"]["table"])
                sql_parts.append("")

            # Embeddings table
            if "embeddings" in schema["sql"] and schema["sql"]["embeddings"]:
                sql_parts.append(f"-- Embeddings for {table_name}")
                sql_parts.append(schema["sql"]["embeddings"])
                sql_parts.append("")

            # KV_STORE trigger
            if "kv_trigger" in schema["sql"]:
                sql_parts.append(f"-- KV_STORE trigger for {table_name}")
                sql_parts.append(schema["sql"]["kv_trigger"])
                sql_parts.append("")

        # Add schema table entries (every entity table is also an "agent")
        sql_parts.append("-- ============================================================================")
        sql_parts.append("-- SCHEMA TABLE ENTRIES")
        sql_parts.append("-- Every entity table gets a schemas entry for agent-like access")
        sql_parts.append("-- ============================================================================")
        sql_parts.append("")

        for table_name, schema in self.schemas.items():
            if "schema_metadata" in schema:
                schema_upsert = generate_schema_upsert_sql(schema["schema_metadata"])
                sql_parts.append(schema_upsert)
                sql_parts.append("")

        # Add migration record
        sql_parts.append("-- ============================================================================")
        sql_parts.append("-- RECORD MIGRATION")
        sql_parts.append("-- ============================================================================")
        sql_parts.append("")
        sql_parts.append("INSERT INTO rem_migrations (name, type, version)")
        sql_parts.append("VALUES ('install_models.sql', 'models', '1.0.0')")
        sql_parts.append("ON CONFLICT (name) DO UPDATE")
        sql_parts.append("SET applied_at = CURRENT_TIMESTAMP,")
        sql_parts.append("    applied_by = CURRENT_USER;")
        sql_parts.append("")

        # Completion message
        sql_parts.append("DO $$")
        sql_parts.append("BEGIN")
        sql_parts.append("    RAISE NOTICE '============================================================';")
        sql_parts.append(f"    RAISE NOTICE 'REM Model Schema Applied: {len(self.schemas)} tables';")
        sql_parts.append("    RAISE NOTICE '============================================================';")
        for table_name in sorted(self.schemas.keys()):
            embeddable = len(self.schemas[table_name].get("embeddable_fields", []))
            embed_info = f" ({embeddable} embeddable fields)" if embeddable else ""
            sql_parts.append(f"    RAISE NOTICE '  ✓ {table_name}{embed_info}';")
        sql_parts.append("    RAISE NOTICE '';")
        sql_parts.append("    RAISE NOTICE 'Next: Run background indexes if needed';")
        sql_parts.append("    RAISE NOTICE '  rem db migrate --background-indexes';")
        sql_parts.append("    RAISE NOTICE '============================================================';")
        sql_parts.append("END $$;")

        complete_sql = "\n".join(sql_parts)

        # Write to file if specified
        if output_file:
            output_path = self.output_dir / output_file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(complete_sql)
            logger.info(f"Schema written to {output_path}")

        return complete_sql

    def generate_background_indexes(self) -> str:
        """
        Generate SQL for background index creation.

        These indexes are created CONCURRENTLY to avoid blocking writes.
        Should be run after initial data load.

        Returns:
            SQL for background index creation
        """
        sql_parts = [
            "-- Background index creation",
            "-- Run AFTER initial data load to avoid blocking writes",
            "",
        ]

        for table_name, schema in self.schemas.items():
            if not schema.get("embeddable_fields"):
                continue

            embeddings_table = f"embeddings_{table_name}"

            sql_parts.append(f"-- HNSW vector index for {embeddings_table}")
            sql_parts.append(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_{embeddings_table}_vector_hnsw"
            )
            sql_parts.append(f"ON {embeddings_table}")
            sql_parts.append("USING hnsw (embedding vector_cosine_ops);")
            sql_parts.append("")

        return "\n".join(sql_parts)
