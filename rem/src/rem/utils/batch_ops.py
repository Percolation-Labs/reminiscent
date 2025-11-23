"""
Batch Operations Utilities.

Provides utilities for batch upserting records with:
- Automatic KV store population (via triggers)
- Embedding generation (stubbed - to be implemented)
- Efficient batch processing

Design:
- Uses Pydantic models for type safety
- Delegates SQL generation to utils.sql_types
- Keeps PostgresService clean
- Handles batching automatically
"""

from typing import Any, Type
from uuid import UUID, uuid4, uuid5, NAMESPACE_OID
from datetime import datetime
import hashlib
import json

from loguru import logger
from pydantic import BaseModel


def generate_deterministic_id(
    user_id: str | None, key_values: list[str] | str
) -> UUID:
    """
    Generate deterministic UUID from user_id and business key(s).

    Convention: If a business key field exists (name, uri, etc.), the ID should be
    deterministic based on user_id + key_value(s). This allows upserts to work
    based on the business key rather than requiring explicit ID management.

    Composite Keys:
    - For composite keys (e.g., uri + ordinal), pass list of values
    - Values are concatenated with ":" separator

    Args:
        user_id: User identifier (tenant scoped)
        key_values: Business key value(s) - single string or list for composite keys

    Returns:
        Deterministic UUID v5 based on user_id + key(s)

    Examples:
        >>> id1 = generate_deterministic_id("user-123", "my-document")
        >>> id2 = generate_deterministic_id("user-123", "my-document")
        >>> id1 == id2
        True
        >>> # Composite key
        >>> id3 = generate_deterministic_id("user-123", ["docs://file.pdf", "0"])
        >>> id4 = generate_deterministic_id("user-123", ["docs://file.pdf", "0"])
        >>> id3 == id4
        True
    """
    # Create namespace from user_id (or use NULL namespace if no user)
    namespace_str = user_id or "system"
    namespace = uuid5(NAMESPACE_OID, namespace_str)

    # Handle composite keys
    if isinstance(key_values, list):
        composite_key = ":".join(str(v) for v in key_values)
    else:
        composite_key = str(key_values)

    # Generate deterministic UUID from business key
    return uuid5(namespace, composite_key)


def prepare_record_for_upsert(
    record: BaseModel,
    model: Type[BaseModel],
    entity_key_field: str | None = None,
) -> dict[str, Any]:
    """
    Prepare a Pydantic record for database upsert.

    ID Generation Convention:
    - If entity_key_field is provided: Generate deterministic ID from user_id + key
    - Otherwise: Generate random UUID v4

    This allows business key-based upserts where the same user + key always gets
    the same ID, enabling natural upsert behavior.

    Args:
        record: Pydantic model instance
        model: Pydantic model class
        entity_key_field: Optional business key field name (name, uri, etc.)

    Returns:
        Dict with field values ready for SQL insertion

    Example:
        >>> from rem.models.entities import Resource
        >>> resource = Resource(name="test", content="data", tenant_id="acme", user_id="sarah")
        >>> data = prepare_record_for_upsert(resource, Resource, entity_key_field="name")
        >>> "id" in data  # ID generated from user_id + name
        True
    """
    # Convert to dict
    data = record.model_dump()

    # Generate ID based on convention
    if "id" not in data or data["id"] is None:
        user_id = data.get("user_id")

        # Check for composite keys (fields with composite_key=True in json_schema_extra)
        composite_key_fields = []
        for field_name, field_info in model.model_fields.items():
            json_extra = getattr(field_info, "json_schema_extra", None)
            if json_extra and isinstance(json_extra, dict):
                if json_extra.get("composite_key") is True:
                    composite_key_fields.append(field_name)

        # Check if we have a business key field
        if entity_key_field and entity_key_field in data:
            key_value = data[entity_key_field]

            if key_value:
                # Build composite key if additional fields exist
                if composite_key_fields:
                    key_values = [str(key_value)]
                    for comp_field in composite_key_fields:
                        if comp_field in data:
                            key_values.append(str(data[comp_field]))

                    # Generate deterministic ID from composite key
                    data["id"] = generate_deterministic_id(user_id, key_values)
                    logger.debug(
                        f"Generated deterministic ID from composite key: "
                        f"{entity_key_field}={key_value} + {composite_key_fields}"
                    )
                else:
                    # Single business key
                    data["id"] = generate_deterministic_id(user_id, str(key_value))
                    logger.debug(
                        f"Generated deterministic ID from {entity_key_field}={key_value}"
                    )
            else:
                # Key field is None, use random UUID
                data["id"] = uuid4()
        else:
            # No business key, use random UUID
            data["id"] = uuid4()

    # Handle UUID serialization
    if "id" in data and isinstance(data["id"], UUID):
        data["id"] = str(data["id"])

    # JSONB fields: asyncpg handles dict/list serialization automatically
    # DO NOT convert to JSON strings - asyncpg expects native Python types
    # PostgreSQL JSONB columns work with Python dicts/lists directly

    # Normalize datetime fields to be timezone-naive (PostgreSQL TIMESTAMP WITHOUT TIME ZONE)
    for field_name, field_value in data.items():
        if isinstance(field_value, datetime) and field_value.tzinfo is not None:
            # Convert timezone-aware datetime to naive UTC
            data[field_name] = field_value.replace(tzinfo=None)

    # Remove None values for optional fields (let DB handle defaults)
    # Keep None for required fields to trigger NOT NULL constraints
    # Also filter out fields that don't exist in DB schema (tags, column)
    SKIP_FIELDS = {"tags", "column"}  # CoreModel fields not in DB schema

    cleaned_data = {}
    for field_name, field_value in data.items():
        # Skip fields that aren't in DB schema
        if field_name in SKIP_FIELDS:
            continue

        field_info = model.model_fields.get(field_name)
        if field_info is not None and field_info.is_required():
            # Keep required fields even if None (will error if truly NULL)
            cleaned_data[field_name] = field_value
        elif field_value is not None:
            # Only include optional fields if they have values
            cleaned_data[field_name] = field_value

    return cleaned_data


def batch_iterator(items: list, batch_size: int = 100):
    """
    Iterate over items in batches.

    Args:
        items: List of items to batch
        batch_size: Size of each batch

    Yields:
        Batches of items

    Example:
        >>> items = list(range(250))
        >>> batches = list(batch_iterator(items, 100))
        >>> len(batches)
        3
        >>> len(batches[0])
        100
        >>> len(batches[2])
        50
    """
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


async def generate_embeddings_stub(
    records: list[BaseModel],
    table_name: str,
    embeddable_fields: list[str],
    provider: str = "openai",
    model: str = "text-embedding-3-small",
) -> list[dict]:
    """
    Generate embeddings for record fields (STUBBED).

    This is a placeholder for the actual embedding generation logic.
    Will be implemented to:
    1. Extract text from embeddable fields
    2. Call OpenAI/Anthropic API in batch
    3. Return embedding records for upsert

    Args:
        records: List of Pydantic records
        table_name: Name of the entity table
        embeddable_fields: List of field names to embed
        provider: Embedding provider (openai, cohere, etc.)
        model: Embedding model name

    Returns:
        List of embedding records (id, entity_id, field_name, provider, model, embedding)

    TODO:
        - Implement OpenAI batch embedding API call
        - Handle rate limiting and retries
        - Support multiple providers
        - Cache embeddings to avoid regeneration
    """
    logger.warning(
        f"Embedding generation is stubbed for {table_name} "
        f"with {len(records)} records and fields {embeddable_fields}"
    )

    # STUB: Return empty list for now
    # When implemented, this will return records like:
    # [
    #     {
    #         "entity_id": record.id,
    #         "field_name": "content",
    #         "provider": "openai",
    #         "model": "text-embedding-3-small",
    #         "embedding": [0.1, 0.2, ...],  # 1536 dimensions
    #     }
    # ]
    return []


def validate_record_for_kv_store(
    record: BaseModel,
    entity_key_field: str,
    tenant_id: str | None = None,
) -> tuple[bool, str]:
    """
    Validate that a record has required fields for KV store population.

    Args:
        record: Pydantic model instance
        entity_key_field: Field name to use as entity_key
        tenant_id: Optional tenant_id override

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> from rem.models.entities import Resource
        >>> resource = Resource(name="test", content="data", tenant_id="acme")
        >>> valid, msg = validate_record_for_kv_store(resource, "name", "acme")
        >>> valid
        True
    """
    # Check entity_key field exists and has value
    if not hasattr(record, entity_key_field):
        return False, f"Record missing entity_key field: {entity_key_field}"

    entity_key_value = getattr(record, entity_key_field)
    if not entity_key_value:
        return False, f"Entity key field '{entity_key_field}' is empty"

    # Check tenant_id (either on record or provided)
    record_tenant_id = getattr(record, "tenant_id", None)
    effective_tenant_id = tenant_id or record_tenant_id

    if not effective_tenant_id:
        return False, "Record must have tenant_id for KV store"

    return True, ""


def build_upsert_statement(
    table_name: str,
    field_names: list[str],
    conflict_column: str = "id",
) -> str:
    """
    Build PostgreSQL UPSERT statement with proper identifier quoting.

    PostgreSQL reserved keywords (like "column", "user", "order") must be quoted.
    We quote all identifiers to avoid SQL injection and reserved keyword issues.

    Args:
        table_name: Name of the table
        field_names: List of field names to insert
        conflict_column: Column to use for conflict detection

    Returns:
        SQL UPSERT statement with placeholders

    Example:
        >>> sql = build_upsert_statement("resources", ["id", "name", "content"])
        >>> "ON CONFLICT" in sql
        True
        >>> "DO UPDATE SET" in sql
        True
    """
    # Quote all identifiers to handle reserved keywords like "column"
    quoted_fields = [f'"{field}"' for field in field_names]
    placeholders = [f"${i+1}" for i in range(len(field_names))]

    # Exclude conflict column from UPDATE
    update_fields = [f for f in field_names if f != conflict_column]
    update_set = ", ".join([f'"{field}" = EXCLUDED."{field}"' for field in update_fields])

    sql = f"""
    INSERT INTO {table_name} ({", ".join(quoted_fields)})
    VALUES ({", ".join(placeholders)})
    ON CONFLICT ("{conflict_column}")
    DO UPDATE SET {update_set}
    RETURNING *;
    """

    return sql.strip()
