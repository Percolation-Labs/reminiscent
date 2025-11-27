"""
Pydantic to PostgreSQL Type Mapping Utility.

Maps Pydantic field types to PostgreSQL column types with intelligent defaults:
- Strings: VARCHAR(256) by default, TEXT for content/description fields
- Union types: Prefer UUID, JSONB over other types
- Lists of strings: TEXT[] (PostgreSQL arrays)
- Dicts and lists of dicts: JSONB
- Field metadata: Respect json_schema_extra for custom types and embeddings

Best Practices:
- VARCHAR(256) for most strings (indexes work well, prevents excessive data)
- TEXT for long-form content (descriptions, summaries, content fields)
- JSONB for structured data (better querying than JSON)
- Arrays for simple lists, JSONB for complex nested structures
- UUID for identifiers in Union types
"""

import types
from datetime import date, datetime, time
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel
from pydantic.fields import FieldInfo


# Field names that should use TEXT instead of VARCHAR
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


def get_sql_type(field_info: FieldInfo, field_name: str) -> str:
    """
    Map Pydantic field to PostgreSQL type.

    Args:
        field_info: Pydantic FieldInfo object
        field_name: Name of the field (used for heuristics)

    Returns:
        PostgreSQL type string (e.g., "VARCHAR(256)", "JSONB", "TEXT[]")

    Examples:
        >>> from pydantic import Field
        >>> get_sql_type(Field(default="test"), "name")
        'VARCHAR(256)'
        >>> get_sql_type(Field(default=""), "content")
        'TEXT'
        >>> get_sql_type(Field(default_factory=dict), "metadata")
        'JSONB'
    """
    # Check for explicit sql_type in json_schema_extra
    if field_info.json_schema_extra:
        if isinstance(field_info.json_schema_extra, dict):
            if "sql_type" in field_info.json_schema_extra:
                return field_info.json_schema_extra["sql_type"]

            # Fields with embedding_provider should be TEXT (for vector search preprocessing)
            # Format: "openai:text-embedding-3-small" or "anthropic:voyage-2"
            if "embedding_provider" in field_info.json_schema_extra:
                return "TEXT"

    # Get the annotation (type hint)
    annotation = field_info.annotation

    # Handle None annotation (shouldn't happen, but be safe)
    if annotation is None:
        return "TEXT"

    # Handle Union types (including Optional[T] which is Union[T, None])
    # Also handles Python 3.10+ `X | None` syntax which uses types.UnionType
    origin = get_origin(annotation)
    if origin is Union or isinstance(annotation, types.UnionType):
        args = get_args(annotation)
        # Filter out NoneType
        non_none_args = [arg for arg in args if arg is not type(None)]

        if not non_none_args:
            return "TEXT"

        # Prefer UUID over other types in unions
        if UUID in non_none_args:
            return "UUID"

        # Prefer dict/JSONB over other types in unions
        if dict in non_none_args:
            return "JSONB"

        # Use the first non-None type
        return _map_simple_type(non_none_args[0], field_name)

    # Handle simple types
    return _map_simple_type(annotation, field_name)


def _map_simple_type(python_type: type, field_name: str) -> str:
    """
    Map a simple Python type to PostgreSQL type.

    Args:
        python_type: Python type annotation
        field_name: Field name for heuristics

    Returns:
        PostgreSQL type string
    """
    # Check if it's a generic type (List, Dict, etc.)
    origin = get_origin(python_type)
    args = get_args(python_type)

    # Handle list types
    if origin is list:
        if args:
            inner_type = args[0]

            # List of strings -> PostgreSQL array
            if inner_type is str:
                return "TEXT[]"

            # List of dicts or other complex types -> JSONB
            if inner_type is dict or get_origin(inner_type) is not None:
                return "JSONB"

            # List of primitives (int, float, bool) -> JSONB for simplicity
            return "JSONB"

        # Untyped list -> JSONB
        return "JSONB"

    # Handle dict types -> always JSONB
    if origin is dict or python_type is dict:
        return "JSONB"

    # Handle primitive types
    type_mapping = {
        str: _get_string_type(field_name),
        int: "INTEGER",
        float: "DOUBLE PRECISION",
        bool: "BOOLEAN",
        UUID: "UUID",
        datetime: "TIMESTAMP",
        date: "DATE",
        time: "TIME",
        bytes: "BYTEA",
    }

    # Check direct type match
    if python_type in type_mapping:
        return type_mapping[python_type]

    # Check if it's a Pydantic model -> JSONB
    if isinstance(python_type, type) and issubclass(python_type, BaseModel):
        return "JSONB"

    # Default to TEXT for unknown types
    return "TEXT"


def _get_string_type(field_name: str) -> str:
    """
    Determine string type based on field name.

    Args:
        field_name: Name of the field

    Returns:
        "TEXT" for long-form content, "VARCHAR(256)" for others
    """
    # Check if field name indicates long-form content
    field_lower = field_name.lower()

    if field_lower in LONG_TEXT_FIELD_NAMES:
        return "TEXT"

    # Check for common suffixes
    if field_lower.endswith(("_content", "_description", "_summary", "_text", "_message")):
        return "TEXT"

    # Default to VARCHAR with reasonable length
    return "VARCHAR(256)"


def get_column_definition(
    field_info: FieldInfo,
    field_name: str,
    nullable: bool = True,
    primary_key: bool = False,
) -> str:
    """
    Generate complete PostgreSQL column definition.

    Args:
        field_info: Pydantic FieldInfo object
        field_name: Name of the column
        nullable: Whether column allows NULL
        primary_key: Whether this is a primary key

    Returns:
        Complete column definition SQL

    Examples:
        >>> from pydantic import Field
        >>> get_column_definition(Field(default=""), "name", nullable=False)
        'name VARCHAR(256) NOT NULL'
        >>> get_column_definition(Field(default_factory=dict), "metadata")
        'metadata JSONB NOT NULL DEFAULT \\'{}\\'::jsonb'
    """
    sql_type = get_sql_type(field_info, field_name)

    parts = [field_name, sql_type]

    if primary_key:
        parts.append("PRIMARY KEY")
    elif not nullable:
        parts.append("NOT NULL")

    # Add defaults for JSONB and arrays
    if field_info.default_factory is not None:
        if sql_type == "JSONB":
            parts.append("DEFAULT '{}'::jsonb")
        elif sql_type.endswith("[]"):
            parts.append("DEFAULT ARRAY[]::TEXT[]")

    return " ".join(parts)


def model_to_create_table(
    model: type[BaseModel],
    table_name: str,
    include_indexes: bool = True,
) -> str:
    """
    Generate CREATE TABLE statement from Pydantic model.

    Args:
        model: Pydantic model class
        table_name: Name of the table to create
        include_indexes: Whether to include index creation statements

    Returns:
        SQL CREATE TABLE statement

    Examples:
        >>> from pydantic import BaseModel, Field
        >>> class User(BaseModel):
        ...     id: str = Field(..., description="User ID")
        ...     name: str
        ...     metadata: dict = Field(default_factory=dict)
        >>> sql = model_to_create_table(User, "users")
        >>> "CREATE TABLE" in sql
        True
    """
    columns = []
    indexes = []

    for field_name, field_info in model.model_fields.items():
        # Determine if field is required (not nullable)
        nullable = not field_info.is_required() or field_info.default is not None

        # Check if this is the primary key (usually 'id')
        is_pk = field_name == "id"

        column_def = get_column_definition(field_info, field_name, nullable, is_pk)
        columns.append(f"    {column_def}")

        # Generate indexes for common query patterns
        if include_indexes and not is_pk:
            sql_type = get_sql_type(field_info, field_name)

            # Index for foreign keys and frequently queried fields
            if field_name.endswith("_id") or field_name in {"tenant_id", "user_id", "session_id"}:
                indexes.append(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{field_name} "
                    f"ON {table_name}({field_name});"
                )

            # GIN indexes for JSONB and arrays
            if sql_type == "JSONB":
                indexes.append(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{field_name} "
                    f"ON {table_name} USING GIN({field_name});"
                )
            elif sql_type.endswith("[]"):
                indexes.append(
                    f"CREATE INDEX IF NOT EXISTS idx_{table_name}_{field_name} "
                    f"ON {table_name} USING GIN({field_name});"
                )

    # Build CREATE TABLE statement
    create_table = f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
    create_table += ",\n".join(columns)
    create_table += "\n);"

    # Add indexes
    if indexes:
        create_table += "\n\n-- Indexes\n"
        create_table += "\n".join(indexes)

    return create_table


def model_to_upsert(
    model: type[BaseModel],
    table_name: str,
    conflict_column: str = "id",
) -> str:
    """
    Generate INSERT ... ON CONFLICT UPDATE (UPSERT) statement template.

    Args:
        model: Pydantic model class
        table_name: Name of the table
        conflict_column: Column to use for conflict detection (usually 'id')

    Returns:
        SQL UPSERT statement with placeholders

    Examples:
        >>> from pydantic import BaseModel
        >>> class User(BaseModel):
        ...     id: str
        ...     name: str
        >>> sql = model_to_upsert(User, "users")
        >>> "ON CONFLICT" in sql
        True
    """
    field_names = list(model.model_fields.keys())
    placeholders = [f"${i+1}" for i in range(len(field_names))]

    # Exclude conflict column from UPDATE
    update_fields = [f for f in field_names if f != conflict_column]
    update_set = ", ".join([f"{field} = EXCLUDED.{field}" for field in update_fields])

    sql = f"""INSERT INTO {table_name} ({", ".join(field_names)})
VALUES ({", ".join(placeholders)})
ON CONFLICT ({conflict_column})
DO UPDATE SET {update_set};"""

    return sql
