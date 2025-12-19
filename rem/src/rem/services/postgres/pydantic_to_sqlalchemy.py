"""
Convert Pydantic models to SQLAlchemy metadata for Alembic autogenerate.

This module bridges REM's Pydantic-first approach with Alembic's SQLAlchemy requirement
by dynamically building SQLAlchemy Table objects from Pydantic model definitions.

IMPORTANT: Type mappings here MUST stay in sync with utils/sql_types.py
to ensure the diff command produces accurate results.
"""

import types
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Union, get_args, get_origin
from uuid import UUID as UUIDType

from loguru import logger
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

# Import pgvector type for embeddings
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None

from .schema_generator import SchemaGenerator


# Field names that should use TEXT instead of VARCHAR (sync with sql_types.py)
LONG_TEXT_FIELD_NAMES = {
    "content",
    "description",
    "summary",
    "instructions",
    "prompt",
    "message",
    "body",
    "text",
    "note",
    "comment",
}

# System fields handled separately by schema generation
SYSTEM_FIELDS = {
    "id", "created_at", "updated_at", "deleted_at",
    "tenant_id", "user_id", "graph_edges", "metadata", "tags",
}

# Fields that get embeddings by default (sync with register_type.py)
DEFAULT_EMBED_FIELD_NAMES = {
    "content",
    "description",
    "summary",
    "text",
    "body",
    "message",
    "notes",
}

# Embedding configuration (sync with register_type.py)
DEFAULT_EMBEDDING_DIMENSIONS = 1536


def pydantic_type_to_sqlalchemy(
    field_info: FieldInfo,
    field_name: str,
) -> Any:
    """
    Map Pydantic field to SQLAlchemy column type.

    This function mirrors the logic in utils/sql_types.py to ensure
    consistent type mapping between schema generation and diff detection.

    Args:
        field_info: Pydantic FieldInfo object
        field_name: Name of the field (used for heuristics)

    Returns:
        SQLAlchemy column type
    """
    # Check for explicit sql_type in json_schema_extra
    if field_info.json_schema_extra:
        if isinstance(field_info.json_schema_extra, dict):
            sql_type = field_info.json_schema_extra.get("sql_type")
            if sql_type:
                return _sql_string_to_sqlalchemy(sql_type)

            # Fields with embedding_provider should be TEXT
            if "embedding_provider" in field_info.json_schema_extra:
                return Text

    annotation = field_info.annotation

    # Handle None annotation
    if annotation is None:
        return Text

    # Handle Union types (including Optional[T] and Python 3.10+ X | None)
    origin = get_origin(annotation)
    if origin is Union or isinstance(annotation, types.UnionType):
        args = get_args(annotation)
        # Filter out NoneType
        non_none_args = [arg for arg in args if arg is not type(None)]

        if not non_none_args:
            return Text

        # Prefer UUID over other types in unions
        if UUIDType in non_none_args:
            return UUID(as_uuid=True)

        # Prefer dict/JSONB over other types in unions
        if dict in non_none_args:
            return JSONB

        # Use the first non-None type
        return _map_simple_type(non_none_args[0], field_name)

    return _map_simple_type(annotation, field_name)


def _map_simple_type(python_type: type, field_name: str) -> Any:
    """
    Map a simple Python type to SQLAlchemy column type.

    Args:
        python_type: Python type annotation
        field_name: Field name for heuristics

    Returns:
        SQLAlchemy column type
    """
    origin = get_origin(python_type)
    args = get_args(python_type)

    # Handle list types
    if origin is list:
        if args:
            inner_type = args[0]

            # List of strings -> PostgreSQL TEXT[]
            if inner_type is str:
                return ARRAY(Text)

            # List of dicts or complex types -> JSONB
            if inner_type is dict or get_origin(inner_type) is not None:
                return JSONB

            # List of primitives -> JSONB
            return JSONB

        # Untyped list -> JSONB
        return JSONB

    # Handle dict types -> JSONB
    if origin is dict or python_type is dict:
        return JSONB

    # Handle primitive types
    if python_type is str:
        return _get_string_type(field_name)

    if python_type is int:
        return Integer

    if python_type is float:
        return Float

    if python_type is bool:
        return Boolean

    if python_type is UUIDType:
        return UUID(as_uuid=True)

    if python_type is datetime:
        return DateTime

    if python_type is date:
        return Date

    if python_type is time:
        return Time

    if python_type is bytes:
        return LargeBinary

    # Check if it's a Pydantic model -> JSONB
    if isinstance(python_type, type) and issubclass(python_type, BaseModel):
        return JSONB

    # Default to Text for unknown types
    return Text


def _get_string_type(field_name: str) -> Any:
    """
    Determine string type based on field name.

    Args:
        field_name: Name of the field

    Returns:
        Text for long-form content, String(256) for others
    """
    field_lower = field_name.lower()

    if field_lower in LONG_TEXT_FIELD_NAMES:
        return Text

    # Check for common suffixes
    if field_lower.endswith(("_content", "_description", "_summary", "_text", "_message")):
        return Text

    return String(256)


def _sql_string_to_sqlalchemy(sql_type: str) -> Any:
    """
    Convert SQL type string to SQLAlchemy type.

    Args:
        sql_type: PostgreSQL type string (e.g., "VARCHAR(256)", "JSONB")

    Returns:
        SQLAlchemy column type
    """
    sql_upper = sql_type.upper()

    if sql_upper == "TEXT":
        return Text
    if sql_upper == "JSONB" or sql_upper == "JSON":
        return JSONB
    if sql_upper == "UUID":
        return UUID(as_uuid=True)
    if sql_upper == "INTEGER" or sql_upper == "INT":
        return Integer
    if sql_upper == "BOOLEAN" or sql_upper == "BOOL":
        return Boolean
    if sql_upper == "TIMESTAMP":
        return DateTime
    if sql_upper == "DATE":
        return Date
    if sql_upper == "TIME":
        return Time
    if sql_upper == "DOUBLE PRECISION" or sql_upper == "FLOAT":
        return Float
    if sql_upper == "BYTEA":
        return LargeBinary
    if sql_upper.startswith("VARCHAR"):
        # Extract length from VARCHAR(n)
        import re
        match = re.match(r"VARCHAR\((\d+)\)", sql_upper)
        if match:
            return String(int(match.group(1)))
        return String(256)
    if sql_upper == "TEXT[]":
        return ARRAY(Text)

    return Text


def _should_embed_field(field_name: str, field_info: FieldInfo) -> bool:
    """
    Determine if a field should have embeddings generated.

    Mirrors logic in register_type.should_embed_field().

    Rules:
    1. If json_schema_extra.embed = True, always embed
    2. If json_schema_extra.embed = False, never embed
    3. If field name in DEFAULT_EMBED_FIELD_NAMES, embed by default
    4. Otherwise, don't embed
    """
    # Check json_schema_extra for explicit embed configuration
    json_extra = getattr(field_info, "json_schema_extra", None)
    if json_extra and isinstance(json_extra, dict):
        embed = json_extra.get("embed")
        if embed is not None:
            return bool(embed)

    # Default: embed if field name matches common content fields
    return field_name.lower() in DEFAULT_EMBED_FIELD_NAMES


def _get_embeddable_fields(model: type[BaseModel]) -> list[str]:
    """Get list of field names that should have embeddings."""
    embeddable = []
    for field_name, field_info in model.model_fields.items():
        if field_name in SYSTEM_FIELDS:
            continue
        if _should_embed_field(field_name, field_info):
            embeddable.append(field_name)
    return embeddable


def build_sqlalchemy_metadata_from_pydantic(models_dir: Path | None = None) -> MetaData:
    """
    Build SQLAlchemy MetaData from Pydantic models.

    This function uses the model registry as the source of truth:
    1. Core models (Resource, Message, User, etc.) - always included
    2. User-registered models via rem.register_model() - included if registered
    3. Embeddings tables for models with embeddable fields

    The registry ensures only actual entity models are included (not DTOs).

    Args:
        models_dir: Optional, not used (kept for backwards compatibility).
                   Models are discovered via the registry, not directory scanning.

    Returns:
        SQLAlchemy MetaData object
    """
    from ...registry import get_model_registry

    metadata = MetaData()
    generator = SchemaGenerator()
    registry = get_model_registry()

    # Get all registered models (core + user-registered)
    registered_models = registry.get_models(include_core=True)
    logger.info(f"Registry contains {len(registered_models)} models")

    for model_name, ext in registered_models.items():
        # Use table_name from extension if provided, otherwise infer
        table_name = ext.table_name or generator.infer_table_name(ext.model)

        # Build primary table
        _build_table(ext.model, table_name, metadata)

        # Build embeddings table if model has embeddable fields
        embeddable_fields = _get_embeddable_fields(ext.model)
        if embeddable_fields:
            _build_embeddings_table(table_name, metadata)

    logger.info(f"Built metadata with {len(metadata.tables)} tables")
    return metadata


def _build_table(model: type[BaseModel], table_name: str, metadata: MetaData) -> Table:
    """
    Build SQLAlchemy Table from Pydantic model.

    Mirrors the schema generated by register_type.generate_table_schema().

    Args:
        model: Pydantic model class
        table_name: Table name
        metadata: SQLAlchemy MetaData to add table to

    Returns:
        SQLAlchemy Table object
    """
    columns = []
    indexes = []

    # Primary key: id UUID
    columns.append(
        Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=text("uuid_generate_v4()"),
        )
    )

    # Tenant and user scoping (tenant_id nullable - NULL means public/shared)
    columns.append(Column("tenant_id", String(100), nullable=True))
    columns.append(Column("user_id", String(256), nullable=True))

    # Process Pydantic fields (skip system fields)
    for field_name, field_info in model.model_fields.items():
        if field_name in SYSTEM_FIELDS:
            continue

        sa_type = pydantic_type_to_sqlalchemy(field_info, field_name)
        nullable = not field_info.is_required()

        # Handle default values for JSONB and arrays
        server_default = None
        if field_info.default_factory is not None:
            if isinstance(sa_type, type) and sa_type is JSONB:
                server_default = text("'{}'::jsonb")
            elif isinstance(sa_type, JSONB):
                server_default = text("'{}'::jsonb")
            elif isinstance(sa_type, ARRAY):
                server_default = text("ARRAY[]::TEXT[]")

        columns.append(
            Column(field_name, sa_type, nullable=nullable, server_default=server_default)
        )

    # System timestamp fields
    columns.append(Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")))
    columns.append(Column("updated_at", DateTime, server_default=text("CURRENT_TIMESTAMP")))
    columns.append(Column("deleted_at", DateTime, nullable=True))

    # graph_edges JSONB field
    columns.append(
        Column("graph_edges", JSONB, nullable=True, server_default=text("'[]'::jsonb"))
    )

    # metadata JSONB field
    columns.append(
        Column("metadata", JSONB, nullable=True, server_default=text("'{}'::jsonb"))
    )

    # tags TEXT[] field
    columns.append(
        Column("tags", ARRAY(Text), nullable=True, server_default=text("ARRAY[]::TEXT[]"))
    )

    # Create table
    table = Table(table_name, metadata, *columns)

    # Add indexes (matching register_type output)
    Index(f"idx_{table_name}_tenant", table.c.tenant_id)
    Index(f"idx_{table_name}_user", table.c.user_id)
    Index(f"idx_{table_name}_graph_edges", table.c.graph_edges, postgresql_using="gin")
    Index(f"idx_{table_name}_metadata", table.c.metadata, postgresql_using="gin")
    Index(f"idx_{table_name}_tags", table.c.tags, postgresql_using="gin")

    return table


def _build_embeddings_table(base_table_name: str, metadata: MetaData) -> Table:
    """
    Build SQLAlchemy Table for embeddings.

    Mirrors the schema generated by register_type.generate_embeddings_schema().

    Args:
        base_table_name: Name of the primary entity table (e.g., "resources")
        metadata: SQLAlchemy MetaData to add table to

    Returns:
        SQLAlchemy Table object for embeddings_<base_table_name>
    """
    embeddings_table_name = f"embeddings_{base_table_name}"

    # Use pgvector Vector type if available, otherwise use a placeholder
    if HAS_PGVECTOR and Vector is not None:
        vector_type = Vector(DEFAULT_EMBEDDING_DIMENSIONS)
    else:
        # Fallback: use raw SQL type via TypeDecorator or just skip
        # For now, we'll log a warning and use a simple column
        logger.warning(
            f"pgvector not installed, embeddings table {embeddings_table_name} "
            "will use ARRAY type instead of vector"
        )
        vector_type = ARRAY(Float)

    columns = [
        Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=text("uuid_generate_v4()"),
        ),
        Column(
            "entity_id",
            UUID(as_uuid=True),
            ForeignKey(f"{base_table_name}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("field_name", String(100), nullable=False),
        Column("provider", String(50), nullable=False, server_default=text("'openai'")),
        Column("model", String(100), nullable=False, server_default=text("'text-embedding-3-small'")),
        Column("embedding", vector_type, nullable=False),
        Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
        Column("updated_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
    ]

    # Create table with unique constraint
    # Truncate constraint name to fit PostgreSQL's 63-char identifier limit
    constraint_name = f"uq_{base_table_name[:30]}_emb_entity_field_prov"
    table = Table(
        embeddings_table_name,
        metadata,
        *columns,
        UniqueConstraint("entity_id", "field_name", "provider", name=constraint_name),
    )

    # Add indexes (matching register_type output)
    Index(f"idx_{embeddings_table_name}_entity", table.c.entity_id)
    Index(f"idx_{embeddings_table_name}_field_provider", table.c.field_name, table.c.provider)

    return table


def _import_model_modules() -> list[str]:
    """
    Import modules specified in MODELS__IMPORT_MODULES setting.

    This ensures downstream models decorated with @rem.register_model
    are registered before schema generation.

    Returns:
        List of successfully imported module names
    """
    import importlib
    from ...settings import settings

    imported = []
    for module_name in settings.models.module_list:
        try:
            importlib.import_module(module_name)
            imported.append(module_name)
            logger.debug(f"Imported model module: {module_name}")
        except ImportError as e:
            logger.warning(f"Failed to import model module '{module_name}': {e}")
    return imported


def get_target_metadata() -> MetaData:
    """
    Get SQLAlchemy metadata for Alembic autogenerate.

    This is the main entry point used by alembic/env.py and rem db diff.

    Uses the model registry as the source of truth, which includes:
    - Core REM models (Resource, Message, User, etc.)
    - User-registered models via @rem.register_model decorator

    Before building metadata, imports model modules from settings to ensure
    downstream models are registered. This supports:
    - Auto-detection of ./models directory (convention)
    - MODELS__IMPORT_MODULES env var (explicit configuration)

    Returns:
        SQLAlchemy MetaData object representing all registered Pydantic models
    """
    # Import model modules first (auto-detects ./models or uses MODELS__IMPORT_MODULES)
    imported = _import_model_modules()
    if imported:
        logger.info(f"Imported model modules: {imported}")

    # build_sqlalchemy_metadata_from_pydantic uses the registry internally,
    # so no directory path is needed (the parameter is kept for backwards compat)
    return build_sqlalchemy_metadata_from_pydantic()
