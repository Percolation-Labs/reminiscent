"""
Dynamic table and embeddings schema generator from Pydantic models.

Generates:
1. Primary table for entity storage
2. embeddings_<table> for vector embeddings (one row per field per provider)
3. Registers entity in KV_STORE cache
4. Background index creation for performance

Design Patterns:
- Fields marked with json_schema_extra={\"embed\": True} get embeddings
- Content fields (TextField, description, etc.) embed by default
- Multiple embedding providers supported (OpenAI, Cohere, etc.)
- UNLOGGED KV_STORE for O(1) lookups
- Background index creation to avoid blocking writes
"""

from typing import Any, Type

from loguru import logger
from pydantic import BaseModel

from ...utils.sql_types import get_column_definition

# Embedding configuration
DEFAULT_EMBEDDING_PROVIDER = "openai"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536

# Fields that embed by default (if not explicitly disabled)
DEFAULT_EMBED_FIELD_NAMES = {
    "content",
    "description",
    "summary",
    "text",
    "body",
    "message",
    "notes",
}


def should_embed_field(field_name: str, field_info: Any) -> bool:
    """
    Determine if a field should have embeddings generated.

    Rules:
    1. If json_schema_extra.embed = True, always embed
    2. If json_schema_extra.embed = False, never embed
    3. If field name in DEFAULT_EMBED_FIELD_NAMES, embed by default
    4. Otherwise, don't embed

    Args:
        field_name: Field name from Pydantic model
        field_info: Field metadata from model.model_fields

    Returns:
        True if field should have embeddings
    """
    # Check json_schema_extra for explicit embed configuration
    json_extra = getattr(field_info, "json_schema_extra", None)
    if json_extra:
        if isinstance(json_extra, dict):
            embed = json_extra.get("embed")
            if embed is not None:
                return bool(embed)

    # Default: embed if field name matches common content fields
    return field_name.lower() in DEFAULT_EMBED_FIELD_NAMES


def generate_table_schema(
    model: Type[BaseModel], table_name: str, tenant_scoped: bool = True
) -> str:
    """
    Generate CREATE TABLE SQL for Pydantic model.

    Args:
        model: Pydantic model class
        table_name: Table name (e.g., "resources", "moments")
        tenant_scoped: If True, add tenant_id column and indexes

    Returns:
        SQL CREATE TABLE statement
    """
    columns = []
    indexes = []

    # System fields that we add separately (skip if in model)
    SYSTEM_FIELDS = {
        "id", "created_at", "updated_at", "deleted_at",
        "tenant_id", "user_id", "graph_edges", "metadata", "tags", "column"
    }

    # Always add id as primary key
    columns.append("id UUID PRIMARY KEY DEFAULT uuid_generate_v4()")

    # Add tenant_id if tenant scoped (nullable - NULL means public/shared)
    if tenant_scoped:
        columns.append("tenant_id VARCHAR(100)")
        indexes.append(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tenant ON {table_name} (tenant_id);")

    # Add user_id (owner field)
    columns.append("user_id VARCHAR(256)")
    indexes.append(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_user ON {table_name} (user_id);")

    # Process Pydantic fields (skip system fields)
    for field_name, field_info in model.model_fields.items():
        if field_name in SYSTEM_FIELDS:
            continue  # Skip system fields - we add them separately

        # Use sql_types utility for consistent type mapping
        column_def = get_column_definition(
            field_info,
            field_name,
            nullable=not field_info.is_required(),
            primary_key=False
        )
        columns.append(column_def)

    # Add system fields (timestamps)
    columns.append("created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    columns.append("updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    columns.append("deleted_at TIMESTAMP")

    # Add graph_edges JSONB field
    columns.append("graph_edges JSONB DEFAULT '[]'::jsonb")
    indexes.append(
        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_graph_edges ON {table_name} USING GIN (graph_edges);"
    )

    # Add metadata JSONB field
    columns.append("metadata JSONB DEFAULT '{}'::jsonb")
    indexes.append(
        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_metadata ON {table_name} USING GIN (metadata);"
    )

    # Add tags field (TEXT[] for list[str])
    columns.append("tags TEXT[] DEFAULT ARRAY[]::TEXT[]")
    indexes.append(
        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tags ON {table_name} USING GIN (tags);"
    )

    # Generate CREATE TABLE statement
    create_table = f"""
CREATE TABLE IF NOT EXISTS {table_name} (
    {',\n    '.join(columns)}
);
""".strip()

    # Generate indexes
    index_sql = "\n".join(indexes)

    return f"{create_table}\n\n{index_sql}"


def generate_embeddings_schema(
    model: Type[BaseModel], table_name: str, embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
) -> tuple[str, list[str]]:
    """
    Generate embeddings table schema for a model.

    Creates embeddings_<table_name> with:
    - One row per entity per field per provider
    - Unique constraint on (entity_id, field_name, provider)
    - Vector column with pgvector
    - HNSW index for fast similarity search

    Args:
        model: Pydantic model class
        table_name: Base table name
        embedding_provider: Default provider (e.g., "openai", "cohere")

    Returns:
        Tuple of (CREATE TABLE sql, list of embeddable field names)
    """
    embeddings_table = f"embeddings_{table_name}"
    embeddable_fields = []

    # Find fields that should have embeddings
    for field_name, field_info in model.model_fields.items():
        if should_embed_field(field_name, field_info):
            embeddable_fields.append(field_name)

    if not embeddable_fields:
        logger.warning(f"No embeddable fields found for {table_name}")
        return "", []

    # Generate embeddings table
    create_sql = f"""
CREATE TABLE IF NOT EXISTS {embeddings_table} (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES {table_name}(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT '{embedding_provider}',
    model VARCHAR(100) NOT NULL DEFAULT '{DEFAULT_EMBEDDING_MODEL}',
    embedding vector({DEFAULT_EMBEDDING_DIMENSIONS}) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique: one embedding per entity per field per provider
    UNIQUE (entity_id, field_name, provider)
);

-- Index for entity lookup (get all embeddings for entity)
CREATE INDEX IF NOT EXISTS idx_{embeddings_table}_entity ON {embeddings_table} (entity_id);

-- Index for field + provider lookup
CREATE INDEX IF NOT EXISTS idx_{embeddings_table}_field_provider ON {embeddings_table} (field_name, provider);

-- HNSW index for vector similarity search (created in background)
-- Note: This will be created by background thread after data load
-- CREATE INDEX idx_{embeddings_table}_vector_hnsw ON {embeddings_table}
-- USING hnsw (embedding vector_cosine_ops);
""".strip()

    logger.info(
        f"Generated embeddings schema for {table_name} with fields: {embeddable_fields}"
    )

    return create_sql, embeddable_fields


# NOTE: _map_pydantic_to_postgres_type is now replaced by utils.sql_types.get_sql_type
# Removed to use the centralized utility instead


def generate_kv_store_upsert(
    table_name: str,
    entity_key_field: str = "name",
) -> str:
    """
    Generate trigger to maintain KV_STORE cache on entity changes.

    Creates a trigger that:
    1. Extracts entity_key from entity (e.g., name, key, label)
    2. Updates KV_STORE on INSERT/UPDATE for O(1) lookups
    3. Removes from KV_STORE on DELETE

    Args:
        table_name: Base table name
        entity_key_field: Field to use as entity_key in KV_STORE

    Returns:
        SQL for trigger creation
    """
    trigger_name = f"trg_{table_name}_kv_store"
    function_name = f"fn_{table_name}_kv_store_upsert"

    return f"""
-- Trigger function to maintain KV_STORE for {table_name}
CREATE OR REPLACE FUNCTION {function_name}()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        -- Remove from KV_STORE on delete
        DELETE FROM kv_store
        WHERE entity_id = OLD.id;
        RETURN OLD;
    ELSIF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        -- Upsert to KV_STORE (O(1) lookup by entity_key)
        -- tenant_id can be NULL (meaning public/shared data)
        INSERT INTO kv_store (
            entity_key,
            entity_type,
            entity_id,
            tenant_id,
            user_id,
            metadata,
            graph_edges,
            updated_at
        ) VALUES (
            normalize_key(NEW.{entity_key_field}::VARCHAR),
            '{table_name}',
            NEW.id,
            NEW.tenant_id,
            NEW.user_id,
            NEW.metadata,
            COALESCE(NEW.graph_edges, '[]'::jsonb),
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (COALESCE(tenant_id, ''), entity_key)
        DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            user_id = EXCLUDED.user_id,
            metadata = EXCLUDED.metadata,
            graph_edges = EXCLUDED.graph_edges,
            updated_at = CURRENT_TIMESTAMP;

        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};
CREATE TRIGGER {trigger_name}
AFTER INSERT OR UPDATE OR DELETE ON {table_name}
FOR EACH ROW EXECUTE FUNCTION {function_name}();
""".strip()


async def register_type(
    model: Type[BaseModel],
    table_name: str,
    entity_key_field: str = "name",
    tenant_scoped: bool = True,
    create_embeddings: bool = True,
    create_kv_trigger: bool = True,
) -> dict[str, Any]:
    """
    Register a Pydantic model as a database schema.

    Creates:
    1. Primary table for entity storage
    2. Embeddings table (if create_embeddings=True)
    3. KV_STORE trigger (if create_kv_trigger=True)

    Args:
        model: Pydantic model class
        table_name: Table name
        entity_key_field: Field to use as natural key in KV_STORE
        tenant_scoped: Add tenant_id column and indexes
        create_embeddings: Create embeddings table
        create_kv_trigger: Create KV_STORE trigger

    Returns:
        Dict with SQL statements and metadata
    """
    result = {
        "table_name": table_name,
        "model": model.__name__,
        "sql": {},
        "embeddable_fields": [],
    }

    # Generate primary table schema
    table_sql = generate_table_schema(model, table_name, tenant_scoped)
    result["sql"]["table"] = table_sql

    # Generate embeddings schema
    if create_embeddings:
        embeddings_sql, embeddable_fields = generate_embeddings_schema(model, table_name)
        result["sql"]["embeddings"] = embeddings_sql
        result["embeddable_fields"] = embeddable_fields

    # Generate KV_STORE trigger
    if create_kv_trigger:
        kv_trigger_sql = generate_kv_store_upsert(table_name, entity_key_field)
        result["sql"]["kv_trigger"] = kv_trigger_sql

    logger.info(f"Registered type {model.__name__} as table {table_name}")

    return result
