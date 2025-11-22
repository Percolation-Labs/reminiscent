"""
Convert Pydantic models to SQLAlchemy metadata for Alembic autogenerate.

This module bridges REM's Pydantic-first approach with Alembic's SQLAlchemy requirement
by dynamically building SQLAlchemy Table objects from Pydantic model definitions.
"""

from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from .schema_generator import SchemaGenerator


def pydantic_type_to_sqlalchemy(
    field_type: Any, field_info: Any
) -> Any:
    """
    Map Pydantic field type to SQLAlchemy column type.

    Args:
        field_type: Pydantic field type annotation
        field_info: Pydantic FieldInfo object

    Returns:
        SQLAlchemy column type
    """
    # Get the origin type (handles Optional, List, etc.)
    import typing

    origin = typing.get_origin(field_type)
    args = typing.get_args(field_type)

    # Handle Optional types
    if origin is typing.Union:
        # Optional[X] is Union[X, None]
        non_none_types = [t for t in args if t is not type(None)]
        if non_none_types:
            field_type = non_none_types[0]
            origin = typing.get_origin(field_type)
            args = typing.get_args(field_type)

    # Handle list types -> PostgreSQL ARRAY
    if origin is list:
        if args:
            inner_type = args[0]
            if inner_type is str:
                return ARRAY(Text)
            elif inner_type is int:
                return ARRAY(Integer)
            elif inner_type is float:
                return ARRAY(Float)
        return ARRAY(Text)  # Default to text array

    # Handle dict types -> JSONB
    if origin is dict or field_type is dict:
        return JSONB

    # Handle basic types
    if field_type is str:
        # Check if there's a max_length constraint
        max_length = getattr(field_info, "max_length", None)
        if max_length:
            return String(max_length)
        return Text

    if field_type is int:
        return Integer

    if field_type is float:
        return Float

    if field_type is bool:
        return Boolean

    # Handle datetime
    from datetime import datetime

    if field_type is datetime:
        return DateTime

    # Handle UUID
    from uuid import UUID as UUIDType

    if field_type is UUIDType:
        return UUID(as_uuid=True)

    # Handle enums
    import enum

    if isinstance(field_type, type) and issubclass(field_type, enum.Enum):
        return String(50)

    # Default to Text for unknown types
    logger.warning(f"Unknown field type {field_type}, defaulting to Text")
    return Text


def build_sqlalchemy_metadata_from_pydantic(models_dir: Path) -> MetaData:
    """
    Build SQLAlchemy MetaData from Pydantic models.

    This function:
    1. Discovers Pydantic models in the given directory
    2. Infers table names and column definitions
    3. Creates SQLAlchemy Table objects
    4. Returns a MetaData object for Alembic

    Args:
        models_dir: Directory containing Pydantic models

    Returns:
        SQLAlchemy MetaData object
    """
    metadata = MetaData()
    generator = SchemaGenerator()

    # Discover models
    models = generator.discover_models(models_dir)
    logger.info(f"Discovered {len(models)} models for metadata generation")

    for model_name, model_class in models.items():
        # Infer table name
        table_name = generator.infer_table_name(model_class)
        logger.debug(f"Building table {table_name} from model {model_name}")

        # Build columns
        columns = []

        for field_name, field_info in model_class.model_fields.items():
            # Get field type
            field_type = field_info.annotation

            # Map to SQLAlchemy type
            sa_type = pydantic_type_to_sqlalchemy(field_type, field_info)

            # Determine nullable
            nullable = not field_info.is_required()

            # Get default value
            from pydantic_core import PydanticUndefined

            default = None
            if field_info.default is not PydanticUndefined and field_info.default is not None:
                default = field_info.default
            elif field_info.default_factory is not None:
                # For default_factory, we'll use the server default if possible
                factory = field_info.default_factory
                # Handle common default factories
                if factory.__name__ == "list":
                    default = "ARRAY[]::TEXT[]"  # PostgreSQL empty array
                elif factory.__name__ == "dict":
                    default = "'{}'::jsonb"  # PostgreSQL empty JSON
                else:
                    default = None

            # Handle special fields
            server_default = None
            primary_key = False

            if field_name == "id":
                primary_key = True
                if sa_type == UUID(as_uuid=True):
                    server_default = "uuid_generate_v4()"
            elif field_name in ("created_at", "updated_at"):
                server_default = "CURRENT_TIMESTAMP"
            elif isinstance(default, str) and default.startswith("ARRAY["):
                server_default = default
                default = None
            elif isinstance(default, str) and "::jsonb" in default:
                server_default = default
                default = None

            # Create column - only pass server_default if it's a string SQL expression
            column_kwargs = {
                "type_": sa_type,
                "primary_key": primary_key,
                "nullable": nullable,
            }

            if server_default is not None:
                from sqlalchemy import text
                column_kwargs["server_default"] = text(server_default)

            column = Column(field_name, **column_kwargs)

            columns.append(column)

        # Create table
        if columns:
            Table(table_name, metadata, *columns)
            logger.debug(f"Created table {table_name} with {len(columns)} columns")

    logger.info(f"Built metadata with {len(metadata.tables)} tables")
    return metadata


def get_target_metadata() -> MetaData:
    """
    Get SQLAlchemy metadata for Alembic autogenerate.

    This is the main entry point used by alembic/env.py.

    Returns:
        SQLAlchemy MetaData object representing current Pydantic models
    """
    # Find models directory
    import rem

    package_root = Path(rem.__file__).parent.parent.parent
    models_dir = package_root / "src" / "rem" / "models" / "entities"

    if not models_dir.exists():
        logger.error(f"Models directory not found: {models_dir}")
        return MetaData()

    return build_sqlalchemy_metadata_from_pydantic(models_dir)
