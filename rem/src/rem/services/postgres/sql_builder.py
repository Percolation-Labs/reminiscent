"""SQL query builder for Pydantic models.

Generates INSERT, UPDATE, SELECT queries from Pydantic model instances.
Handles serialization and parameter binding automatically.
"""

import hashlib
import json
import uuid
from typing import Any, Type

from pydantic import BaseModel


def get_natural_key(model: BaseModel) -> str | None:
    """
    Get natural key from model following precedence: uri -> key -> name.

    Used for generating deterministic IDs from business keys.
    Does NOT include 'id' since that's what we're trying to generate.

    Args:
        model: Pydantic model instance

    Returns:
        Natural key string or None
    """
    for field in ["uri", "key", "name"]:
        if hasattr(model, field):
            value = getattr(model, field)
            if value:
                return str(value)
    return None


def get_entity_key(model: BaseModel) -> str:
    """
    Get entity key for KV store following precedence: name -> key -> uri -> id.

    For KV store lookups, we prefer human-readable identifiers first (name/key),
    then URIs, with id as the fallback. This allows users to lookup entities
    by their natural names like "panic-disorder" instead of UUIDs.

    Args:
        model: Pydantic model instance

    Returns:
        Entity key string (guaranteed to exist)
    """
    for field in ["name", "key", "uri", "id"]:
        if hasattr(model, field):
            value = getattr(model, field)
            if value:
                return str(value)
    # Should never reach here since id always exists in CoreModel
    raise ValueError(f"Model {type(model)} has no name, key, uri, or id field")


def generate_deterministic_id(user_id: str | None, entity_key: str) -> uuid.UUID:
    """
    Generate deterministic UUID from hash of (user_id, entity_key).

    Args:
        user_id: User identifier (optional)
        entity_key: Entity key field value

    Returns:
        Deterministic UUID
    """
    # Combine user_id and key for hashing
    combined = f"{user_id or 'system'}:{entity_key}"
    hash_bytes = hashlib.sha256(combined.encode()).digest()
    # Use first 16 bytes for UUID
    return uuid.UUID(bytes=hash_bytes[:16])


def model_to_dict(model: BaseModel, exclude_none: bool = True) -> dict[str, Any]:
    """
    Convert Pydantic model to dict suitable for SQL insertion.

    Generates deterministic ID if not present, based on hash(user_id, key).
    Serializes JSONB fields (list[dict], dict) to JSON strings for asyncpg.

    Args:
        model: Pydantic model instance
        exclude_none: Exclude None values (default: True)

    Returns:
        Dict of field_name -> value with JSONB fields as JSON strings
    """
    # Use python mode to preserve datetime objects
    data = model.model_dump(exclude_none=exclude_none, mode="python")

    # Generate deterministic ID if not present
    if not data.get("id"):
        natural_key = get_natural_key(model)
        if natural_key:
            user_id = data.get("user_id")
            data["id"] = generate_deterministic_id(user_id, natural_key)
        else:
            # Fallback to random UUID if no natural key (uri/key/name)
            data["id"] = uuid.uuid4()

    # Note: JSONB conversion is handled by asyncpg codec (set_type_codec in PostgresService)
    # No need to manually convert dicts/lists to JSON strings

    return data


def build_insert(
    model: BaseModel, table_name: str, return_id: bool = True
) -> tuple[str, list[Any]]:
    """
    Build INSERT query from Pydantic model.

    Args:
        model: Pydantic model instance
        table_name: Target table name
        return_id: Return the inserted ID (default: True)

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_insert(message, "messages")
        # INSERT INTO messages (id, content, created_at) VALUES ($1, $2, $3) RETURNING id
    """
    data = model_to_dict(model)

    fields = list(data.keys())
    # Quote field names to handle reserved words
    quoted_fields = [f'"{field}"' for field in fields]
    placeholders = [f"${i+1}" for i in range(len(fields))]
    values = [data[field] for field in fields]

    sql = f"INSERT INTO {table_name} ({', '.join(quoted_fields)}) VALUES ({', '.join(placeholders)})"

    if return_id:
        sql += " RETURNING id"

    return sql, values


def build_upsert(
    model: BaseModel,
    table_name: str,
    conflict_field: str = "id",
    return_id: bool = True,
) -> tuple[str, list[Any]]:
    """
    Build INSERT ... ON CONFLICT DO UPDATE (upsert) query from Pydantic model.

    Args:
        model: Pydantic model instance
        table_name: Target table name
        conflict_field: Field to check for conflicts (default: "id")
        return_id: Return the inserted/updated ID (default: True)

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_upsert(message, "messages")
        # INSERT INTO messages (...) VALUES (...)
        # ON CONFLICT (id) DO UPDATE SET field1=$1, field2=$2, ...
        # RETURNING id
    """
    data = model_to_dict(model)

    fields = list(data.keys())
    quoted_fields = [f'"{field}"' for field in fields]
    placeholders = [f"${i+1}" for i in range(len(fields))]
    values = [data[field] for field in fields]

    # Build update clause (exclude conflict field)
    update_fields = [f for f in fields if f != conflict_field]
    update_clauses = [f'"{field}" = EXCLUDED."{field}"' for field in update_fields]

    sql = f"""
        INSERT INTO {table_name} ({', '.join(quoted_fields)})
        VALUES ({', '.join(placeholders)})
        ON CONFLICT ("{conflict_field}") DO UPDATE
        SET {', '.join(update_clauses)}
    """

    if return_id:
        sql += " RETURNING id"

    return sql.strip(), values


def build_select(
    model_class: Type[BaseModel],
    table_name: str,
    filters: dict[str, Any],
    order_by: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> tuple[str, list[Any]]:
    """
    Build SELECT query with filters.

    Args:
        model_class: Pydantic model class (for field validation)
        table_name: Source table name
        filters: Dict of field -> value filters (AND-ed together)
        order_by: Optional ORDER BY clause
        limit: Optional LIMIT
        offset: Optional OFFSET

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_select(
            Message,
            "messages",
            {"session_id": "abc", "tenant_id": "xyz"},
            order_by="created_at DESC",
            limit=10
        )
        # SELECT * FROM messages
        # WHERE session_id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        # ORDER BY created_at DESC
        # LIMIT 10
    """
    where_clauses = ['"deleted_at" IS NULL']  # Soft delete filter
    params = []
    param_idx = 1

    for field, value in filters.items():
        where_clauses.append(f'"{field}" = ${param_idx}')
        params.append(value)
        param_idx += 1

    sql = f"SELECT * FROM {table_name} WHERE {' AND '.join(where_clauses)}"

    if order_by:
        sql += f" ORDER BY {order_by}"

    if limit is not None:
        sql += f" LIMIT ${param_idx}"
        params.append(limit)
        param_idx += 1

    if offset is not None:
        sql += f" OFFSET ${param_idx}"
        params.append(offset)

    return sql, params


def build_update(
    model: BaseModel, table_name: str, id_value: str, tenant_id: str
) -> tuple[str, list[Any]]:
    """
    Build UPDATE query from Pydantic model.

    Args:
        model: Pydantic model instance with updated values
        table_name: Target table name
        id_value: ID of record to update
        tenant_id: Tenant ID for isolation

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_update(message, "messages", "msg-123", "tenant-1")
        # UPDATE messages SET field1=$1, field2=$2, updated_at=NOW()
        # WHERE id=$N AND tenant_id=$N+1 AND deleted_at IS NULL
    """
    data = model_to_dict(model, exclude_none=False)

    # Exclude id from update fields
    update_fields = [k for k in data.keys() if k != "id"]
    params = [data[field] for field in update_fields]

    # Build SET clause
    set_clauses = [f'"{field}" = ${i+1}' for i, field in enumerate(update_fields)]
    set_clauses.append('"updated_at" = NOW()')

    # Add WHERE params
    param_idx = len(params) + 1
    sql = f"""
        UPDATE {table_name}
        SET {', '.join(set_clauses)}
        WHERE "id" = ${param_idx} AND "tenant_id" = ${param_idx+1} AND "deleted_at" IS NULL
        RETURNING "id"
    """

    params.extend([id_value, tenant_id])

    return sql.strip(), params


def build_delete(
    table_name: str, id_value: str, tenant_id: str
) -> tuple[str, list[Any]]:
    """
    Build soft DELETE query (sets deleted_at).

    Args:
        table_name: Target table name
        id_value: ID of record to delete
        tenant_id: Tenant ID for isolation

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_delete("messages", "msg-123", "tenant-1")
        # UPDATE messages SET deleted_at=NOW(), updated_at=NOW()
        # WHERE id=$1 AND tenant_id=$2 AND deleted_at IS NULL
    """
    sql = f"""
        UPDATE {table_name}
        SET "deleted_at" = NOW(), "updated_at" = NOW()
        WHERE "id" = $1 AND "tenant_id" = $2 AND "deleted_at" IS NULL
        RETURNING "id"
    """

    return sql.strip(), [id_value, tenant_id]


def build_count(
    table_name: str, filters: dict[str, Any]
) -> tuple[str, list[Any]]:
    """
    Build COUNT query with filters.

    Args:
        table_name: Source table name
        filters: Dict of field -> value filters (AND-ed together)

    Returns:
        Tuple of (sql_query, parameters)

    Example:
        sql, params = build_count("messages", {"session_id": "abc"})
        # SELECT COUNT(*) FROM messages
        # WHERE session_id = $1 AND deleted_at IS NULL
    """
    where_clauses = ['"deleted_at" IS NULL']
    params = []
    param_idx = 1

    for field, value in filters.items():
        where_clauses.append(f'"{field}" = ${param_idx}')
        params.append(value)
        param_idx += 1

    sql = f"SELECT COUNT(*) FROM {table_name} WHERE {' AND '.join(where_clauses)}"

    return sql, params
