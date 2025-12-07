"""
Agent Manager - Save, load, and manage user-created agents.

This module provides the core functionality for persisting agent schemas
to the database with user scoping.

Usage:
    from rem.agentic.agents.agent_manager import save_agent, get_agent, list_agents

    # Save an agent
    result = await save_agent(
        name="my-assistant",
        description="You are a helpful assistant.",
        user_id="user-123"
    )

    # Get an agent
    agent = await get_agent("my-assistant", user_id="user-123")

    # List user's agents
    agents = await list_agents(user_id="user-123")
"""

from typing import Any
from loguru import logger


DEFAULT_TOOLS = ["search_rem", "register_metadata"]


def build_agent_spec(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    tools: list[str] | None = None,
    tags: list[str] | None = None,
    version: str = "1.0.0",
) -> dict[str, Any]:
    """
    Build a valid agent schema spec.

    Args:
        name: Agent name in kebab-case
        description: System prompt for the agent
        properties: Output schema properties
        required: Required property names
        tools: Tool names (defaults to search_rem, register_metadata)
        tags: Categorization tags
        version: Semantic version

    Returns:
        Valid agent schema spec dict
    """
    # Default properties
    if properties is None:
        properties = {
            "answer": {
                "type": "string",
                "description": "Natural language response to the user"
            }
        }

    # Default required
    if required is None:
        required = ["answer"]

    # Default tools
    if tools is None:
        tools = DEFAULT_TOOLS.copy()

    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": required,
        "json_schema_extra": {
            "kind": "agent",
            "name": name,
            "version": version,
            "tags": tags or [],
            "tools": [{"name": t, "description": f"Tool: {t}"} for t in tools],
        }
    }


async def save_agent(
    name: str,
    description: str,
    user_id: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    tools: list[str] | None = None,
    tags: list[str] | None = None,
    version: str = "1.0.0",
) -> dict[str, Any]:
    """
    Save an agent schema to the database.

    Args:
        name: Agent name in kebab-case (e.g., "code-reviewer")
        description: The agent's system prompt
        user_id: User identifier for scoping
        properties: Output schema properties
        required: Required property names
        tools: Tool names
        tags: Categorization tags
        version: Semantic version

    Returns:
        Dict with status, agent_name, version, message

    Raises:
        RuntimeError: If database is not available
    """
    from rem.models.entities import Schema
    from rem.services.postgres import get_postgres_service

    # Build the spec
    spec = build_agent_spec(
        name=name,
        description=description,
        properties=properties,
        required=required,
        tools=tools,
        tags=tags,
        version=version,
    )

    # Create Schema entity (user-scoped)
    # Note: tenant_id defaults to "default" for anonymous users
    schema_entity = Schema(
        tenant_id=user_id or "default",
        user_id=user_id,
        name=name,
        spec=spec,
        category="agent",
        metadata={
            "version": version,
            "tags": tags or [],
            "created_via": "agent_manager",
        },
    )

    # Save to database
    postgres = get_postgres_service()
    if not postgres:
        raise RuntimeError("Database not available")

    await postgres.connect()
    try:
        await postgres.batch_upsert(
            records=[schema_entity],
            model=Schema,
            table_name="schemas",
            entity_key_field="name",
            generate_embeddings=False,
        )
        logger.info(f"✅ Agent saved: {name} (user={user_id}, version={version})")
    finally:
        await postgres.disconnect()

    return {
        "status": "success",
        "agent_name": name,
        "version": version,
        "message": f"Agent '{name}' saved successfully.",
    }


async def get_agent(
    name: str,
    user_id: str,
) -> dict[str, Any] | None:
    """
    Get an agent schema by name.

    Checks user's schemas first, then falls back to system schemas.

    Args:
        name: Agent name
        user_id: User identifier

    Returns:
        Agent spec dict if found, None otherwise
    """
    from rem.services.postgres import get_postgres_service

    postgres = get_postgres_service()
    if not postgres:
        return None

    await postgres.connect()
    try:
        query = """
            SELECT spec FROM schemas
            WHERE LOWER(name) = LOWER($1)
            AND category = 'agent'
            AND (user_id = $2 OR user_id IS NULL OR tenant_id = 'system')
            ORDER BY CASE WHEN user_id = $2 THEN 0 ELSE 1 END
            LIMIT 1
        """
        row = await postgres.fetchrow(query, name, user_id)
        if row:
            return row["spec"]
        return None
    finally:
        await postgres.disconnect()


async def list_agents(
    user_id: str,
    include_system: bool = True,
) -> list[dict[str, Any]]:
    """
    List available agents for a user.

    Args:
        user_id: User identifier
        include_system: Include system agents

    Returns:
        List of agent metadata dicts
    """
    from rem.services.postgres import get_postgres_service

    postgres = get_postgres_service()
    if not postgres:
        return []

    await postgres.connect()
    try:
        if include_system:
            query = """
                SELECT name, metadata, user_id, tenant_id
                FROM schemas
                WHERE category = 'agent'
                AND (user_id = $1 OR user_id IS NULL OR tenant_id = 'system')
                ORDER BY name
            """
            rows = await postgres.fetch(query, user_id)
        else:
            query = """
                SELECT name, metadata, user_id, tenant_id
                FROM schemas
                WHERE category = 'agent'
                AND user_id = $1
                ORDER BY name
            """
            rows = await postgres.fetch(query, user_id)

        return [
            {
                "name": row["name"],
                "version": row["metadata"].get("version", "1.0.0") if row["metadata"] else "1.0.0",
                "tags": row["metadata"].get("tags", []) if row["metadata"] else [],
                "is_system": row["tenant_id"] == "system" or row["user_id"] is None,
            }
            for row in rows
        ]
    finally:
        await postgres.disconnect()


async def delete_agent(
    name: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Delete a user's agent.

    Only allows deleting user-owned agents, not system agents.

    Args:
        name: Agent name
        user_id: User identifier

    Returns:
        Dict with status and message
    """
    from rem.services.postgres import get_postgres_service

    postgres = get_postgres_service()
    if not postgres:
        raise RuntimeError("Database not available")

    await postgres.connect()
    try:
        # Only delete user's own agents
        query = """
            DELETE FROM schemas
            WHERE LOWER(name) = LOWER($1)
            AND category = 'agent'
            AND user_id = $2
            RETURNING name
        """
        row = await postgres.fetchrow(query, name, user_id)

        if row:
            logger.info(f"🗑️ Agent deleted: {name} (user={user_id})")
            return {
                "status": "success",
                "message": f"Agent '{name}' deleted.",
            }
        else:
            return {
                "status": "error",
                "message": f"Agent '{name}' not found or not owned by you.",
            }
    finally:
        await postgres.disconnect()
