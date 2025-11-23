"""
Pydantic Serialization Utilities for Agent Results.

Critical Pattern:
When returning Pydantic model instances from agent results (especially in MCP tools,
API responses, or any serialization context), ALWAYS serialize them explicitly using
.model_dump() or .model_dump_json() before returning.

Why This Matters:
- FastMCP, FastAPI, and other frameworks may use their own serialization logic
- Pydantic models returned directly may not include all fields during serialization
- Newly added fields might be silently dropped if not explicitly serialized
- result.output or result.data may be a Pydantic model instance, not a dict

Common Anti-Patterns to Avoid:
```python
# ❌ BAD: Returns Pydantic model directly
return {
    "status": "success",
    "response": result.output,  # Pydantic model instance!
}

# ✅ GOOD: Explicitly serialize first
return {
    "status": "success",
    "response": result.output.model_dump(),  # Serialized dict
}
```

Design Rules:
1. Always check if object has .model_dump() or .model_dump_json()
2. Use serialize_agent_result() for consistent handling
3. In streaming contexts, use .model_dump_json() for SSE
4. Document when functions return Pydantic models vs dicts
"""

from typing import Any, cast

from pydantic import BaseModel


def serialize_agent_result(result: Any) -> dict[str, Any] | str:
    """
    Safely serialize an agent result, handling Pydantic models correctly.

    This function ensures that Pydantic model instances are properly serialized
    before being returned from API endpoints, MCP tools, or any other context
    where serialization is critical.

    Args:
        result: Agent result which may be:
            - Pydantic model instance (has .model_dump())
            - Dict (already serialized)
            - Primitive type (str, int, bool, None)
            - List or other collection

    Returns:
        Serialized result as dict or primitive type

    Examples:
        >>> # With Pydantic model result
        >>> agent_result = await agent.run(query)
        >>> serialized = serialize_agent_result(agent_result.output)
        >>> return {"response": serialized}  # Safe to serialize

        >>> # With already-serialized result
        >>> data = {"key": "value"}
        >>> serialized = serialize_agent_result(data)
        >>> assert serialized == data  # No-op for dicts

        >>> # With primitive result
        >>> result = "Hello world"
        >>> serialized = serialize_agent_result(result)
        >>> assert serialized == result  # No-op for primitives
    """
    # Check if this is a Pydantic model instance
    if isinstance(result, BaseModel):
        return result.model_dump()

    # Check if this has a model_dump method (duck typing)
    if hasattr(result, "model_dump") and callable(getattr(result, "model_dump")):
        return cast(dict[str, Any] | str, result.model_dump())

    # Already a dict or primitive - return as-is
    return cast(dict[str, Any] | str, result)


def serialize_agent_result_json(result: Any) -> str:
    """
    Safely serialize an agent result to JSON string, handling Pydantic models correctly.

    Use this variant when you need a JSON string output (e.g., for SSE streaming,
    JSON responses, or storage).

    Args:
        result: Agent result which may be:
            - Pydantic model instance (has .model_dump_json())
            - Dict or other JSON-serializable object
            - Primitive type

    Returns:
        JSON string representation

    Examples:
        >>> # With Pydantic model result
        >>> agent_result = await agent.run(query)
        >>> json_str = serialize_agent_result_json(agent_result.output)
        >>> return Response(content=json_str, media_type="application/json")

        >>> # For SSE streaming
        >>> chunk = serialize_agent_result_json(result.output)
        >>> yield f"data: {chunk}\\n\\n"
    """
    import json

    # Check if this is a Pydantic model instance with model_dump_json
    if isinstance(result, BaseModel):
        return result.model_dump_json()

    # Check if this has a model_dump_json method (duck typing)
    if hasattr(result, "model_dump_json") and callable(
        getattr(result, "model_dump_json")
    ):
        return cast(str, result.model_dump_json())

    # Fall back to standard json.dumps
    return json.dumps(result)


def is_pydantic_model(obj: Any) -> bool:
    """
    Check if an object is a Pydantic model instance.

    Args:
        obj: Object to check

    Returns:
        True if object is a Pydantic model instance

    Examples:
        >>> from pydantic import BaseModel
        >>> class MyModel(BaseModel):
        ...     value: str
        >>> instance = MyModel(value="test")
        >>> assert is_pydantic_model(instance) == True
        >>> assert is_pydantic_model({"value": "test"}) == False
    """
    return isinstance(obj, BaseModel) or (
        hasattr(obj, "model_dump") and hasattr(obj, "model_fields")
    )


def safe_serialize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively serialize a dict that may contain Pydantic models.

    Use this when you have a dict that may contain Pydantic model instances
    nested within it (e.g., as values).

    Args:
        data: Dict that may contain Pydantic models

    Returns:
        Dict with all Pydantic models serialized to dicts

    Examples:
        >>> # Dict with nested Pydantic model
        >>> data = {
        ...     "status": "success",
        ...     "result": some_pydantic_model,  # Will be serialized
        ...     "metadata": {"count": 5}
        ... }
        >>> serialized = safe_serialize_dict(data)
        >>> # All Pydantic models are now dicts
    """
    result = {}
    for key, value in data.items():
        if is_pydantic_model(value):
            result[key] = serialize_agent_result(value)
        elif isinstance(value, dict):
            result[key] = safe_serialize_dict(value)
        elif isinstance(value, list):
            result[key] = [
                serialize_agent_result(item) if is_pydantic_model(item) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


# Example usage patterns for documentation
USAGE_EXAMPLES = """
# Example 1: MCP Tool returning agent result
async def ask_rem_tool(query: str) -> dict[str, Any]:
    from rem.agentic.serialization import serialize_agent_result

    agent = await create_agent()
    result = await agent.run(query)

    # ✅ GOOD: Serialize before returning
    return {
        "status": "success",
        "response": serialize_agent_result(result.output),
        "model": result.model,
    }

# Example 2: API endpoint with Pydantic result
@app.post("/query")
async def query_endpoint(body: QueryRequest):
    from rem.agentic.serialization import serialize_agent_result

    agent = await create_agent()
    result = await agent.run(body.query)

    # ✅ GOOD: Serialize for FastAPI response
    return {
        "data": serialize_agent_result(result.output),
        "usage": result.usage().model_dump() if result.usage() else None,
    }

# Example 3: Streaming with SSE
async def stream_results(agent, query):
    from rem.agentic.serialization import serialize_agent_result_json

    async with agent.iter(query) as run:
        async for event in run:
            if isinstance(event, SomeEvent):
                # ✅ GOOD: Serialize to JSON string for SSE
                json_str = serialize_agent_result_json(event.data)
                yield f"data: {json_str}\\n\\n"

# Example 4: Service layer returning to MCP tool
async def ask_rem(query: str, tenant_id: str) -> dict[str, Any]:
    from rem.agentic.serialization import serialize_agent_result

    agent = await create_agent()
    result = await agent.run(query)

    # ✅ GOOD: Serialize in service layer
    return {
        "query_output": serialize_agent_result(result.data),
        "natural_query": query,
    }
"""
