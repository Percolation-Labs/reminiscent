"""
Example usage of sql_types utility for generating PostgreSQL schema from Pydantic models.

This demonstrates how REM entity models are mapped to PostgreSQL types.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from rem.utils.sql_types import (
    get_column_definition,
    get_sql_type,
    model_to_create_table,
    model_to_upsert,
)


# Example 1: CoreModel with various field types
class CoreModel(BaseModel):
    """Base model demonstrating all common field types."""

    # ID - Union type, should prefer UUID
    id: UUID | str = Field(..., description="Unique identifier")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Optional tenant/user fields
    tenant_id: str | None = Field(default=None, description="Tenant identifier")
    user_id: str | None = Field(default=None, description="User identifier")

    # JSONB fields
    graph_edges: list[dict] = Field(default_factory=list, description="Graph edges")
    metadata: dict = Field(default_factory=dict, description="Flexible metadata")

    # Array fields
    tags: list[str] = Field(default_factory=list, description="Tags")

    # Database schema metadata
    column: dict = Field(default_factory=dict, description="Column metadata")


# Example 2: Resource with content fields
class Resource(BaseModel):
    """Resource entity with long-form text fields."""

    id: str
    name: str  # VARCHAR(256)
    uri: str | None = None  # VARCHAR(256), nullable
    content: str = ""  # TEXT (long-form field name)
    description: str | None = None  # TEXT (long-form field name)
    category: str | None = None  # VARCHAR(256)
    related_entities: list[dict] = Field(default_factory=list)  # JSONB


# Example 3: Schema with embedding provider
class Schema(BaseModel):
    """Schema with embedding field."""

    id: str
    name: str
    content: str = Field(
        default="",
        json_schema_extra={
            "embedding_provider": "openai:text-embedding-3-small"  # Forces TEXT
        },
    )
    spec: dict = Field(..., description="JSON schema specification")  # JSONB
    category: str | None = None


# Example 4: Custom SQL type override
class CustomModel(BaseModel):
    """Model with custom SQL type specification."""

    id: str
    vector_data: list[float] = Field(
        default_factory=list,
        json_schema_extra={"sql_type": "vector(1536)"},  # Custom pgvector type
    )
    json_data: dict = Field(default_factory=dict)


def demonstrate_field_mapping():
    """Show how individual fields map to SQL types."""
    print("=" * 80)
    print("FIELD TYPE MAPPING EXAMPLES")
    print("=" * 80)

    examples = [
        (CoreModel.model_fields["id"], "id", "Union[UUID, str] -> UUID (prefers UUID in unions)"),
        (CoreModel.model_fields["created_at"], "created_at", "datetime -> TIMESTAMP"),
        (CoreModel.model_fields["tenant_id"], "tenant_id", "str | None -> VARCHAR(256)"),
        (CoreModel.model_fields["graph_edges"], "graph_edges", "list[dict] -> JSONB"),
        (CoreModel.model_fields["metadata"], "metadata", "dict -> JSONB"),
        (CoreModel.model_fields["tags"], "tags", "list[str] -> TEXT[]"),
        (Resource.model_fields["content"], "content", "str (field name 'content') -> TEXT"),
        (Resource.model_fields["name"], "name", "str -> VARCHAR(256)"),
        (
            Schema.model_fields["content"],
            "content",
            "str with embedding_provider (openai:text-embedding-3-small) -> TEXT",
        ),
        (
            CustomModel.model_fields["vector_data"],
            "vector_data",
            "list[float] with sql_type -> vector(1536)",
        ),
    ]

    for field_info, field_name, description in examples:
        sql_type = get_sql_type(field_info, field_name)
        print(f"\n{description}")
        print(f"  SQL Type: {sql_type}")


def demonstrate_column_definitions():
    """Show complete column definitions."""
    print("\n" + "=" * 80)
    print("COLUMN DEFINITION EXAMPLES")
    print("=" * 80)

    examples = [
        (CoreModel.model_fields["id"], "id", False, True, "Primary key"),
        (CoreModel.model_fields["created_at"], "created_at", False, False, "Required timestamp"),
        (CoreModel.model_fields["tenant_id"], "tenant_id", True, False, "Optional tenant"),
        (CoreModel.model_fields["metadata"], "metadata", False, False, "JSONB with default"),
        (CoreModel.model_fields["tags"], "tags", False, False, "Array with default"),
    ]

    for field_info, field_name, nullable, is_pk, description in examples:
        col_def = get_column_definition(field_info, field_name, nullable, is_pk)
        print(f"\n{description}:")
        print(f"  {col_def}")


def demonstrate_create_table():
    """Generate CREATE TABLE statements."""
    print("\n" + "=" * 80)
    print("CREATE TABLE EXAMPLES")
    print("=" * 80)

    # Generate for Resource model
    print("\n-- Resource Table")
    print(model_to_create_table(Resource, "resources"))

    # Generate for Schema model
    print("\n\n-- Schema Table")
    print(model_to_create_table(Schema, "schemas"))


def demonstrate_upsert():
    """Generate UPSERT statements."""
    print("\n" + "=" * 80)
    print("UPSERT EXAMPLES")
    print("=" * 80)

    print("\n-- Resource Upsert")
    print(model_to_upsert(Resource, "resources"))

    print("\n-- Schema Upsert")
    print(model_to_upsert(Schema, "schemas"))


if __name__ == "__main__":
    demonstrate_field_mapping()
    demonstrate_column_definitions()
    demonstrate_create_table()
    demonstrate_upsert()

    print("\n" + "=" * 80)
    print("USAGE IN CODE")
    print("=" * 80)
    print(
        """
# Generate schema for all REM entities
from rem.models.entities import Resource, Message, User, File, Moment, Schema
from rem.utils.sql_types import model_to_create_table

for model, table_name in [
    (Resource, "resources"),
    (Message, "messages"),
    (User, "users"),
    (File, "files"),
    (Moment, "moments"),
    (Schema, "schemas"),
]:
    sql = model_to_create_table(model, table_name)
    print(sql)
    print()

# Generate upsert for inserting/updating entities
from rem.utils.sql_types import model_to_upsert

upsert_sql = model_to_upsert(Resource, "resources")
# Use with psycopg:
# cursor.execute(upsert_sql, (id, name, uri, content, ...))
"""
    )
