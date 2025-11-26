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
from pathlib import Path
from typing import Type

from loguru import logger
from pydantic import BaseModel

from ...settings import settings
from .register_type import register_type


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
            output_dir: Optional directory for output files (defaults to settings.sql_dir)
        """
        self.output_dir = output_dir or Path(settings.sql_dir)
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
        2. Field named \"name\"
        3. Field named \"key\"
        4. Field named \"label\"
        5. First string field

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

        # Check for key fields in priority order: id -> uri -> key -> name
        # (matching sql_builder.get_entity_key convention)
        for candidate in ["id", "uri", "key", "name"]:
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
