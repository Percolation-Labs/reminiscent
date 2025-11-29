"""
MCP Tool Wrappers for Pydantic AI.

This module provides functions to convert MCP tool functions and resources
into a format compatible with the Pydantic AI library.
"""

from typing import Any, Callable

from loguru import logger
from pydantic_ai.tools import Tool


def create_pydantic_tool(func: Callable[..., Any]) -> Tool:
    """
    Create a Pydantic AI Tool from a given function.

    This uses the Tool constructor, which inspects the
    function's signature and docstring to create the tool schema.

    Args:
        func: The function to wrap as a tool.

    Returns:
        A Pydantic AI Tool instance.
    """
    logger.debug(f"Creating Pydantic tool from function: {func.__name__}")
    return Tool(func)


def create_mcp_tool_wrapper(
    tool_name: str,
    mcp_tool: Any,
    user_id: str | None = None,
    description_suffix: str | None = None,
) -> Tool:
    """
    Create a Pydantic AI Tool from a FastMCP FunctionTool.

    FastMCP tools are FunctionTool objects that wrap the actual async function.
    We pass the function directly to Pydantic AI's Tool class, which will
    inspect its signature properly. User ID injection happens in the wrapper.

    Args:
        tool_name: Name of the MCP tool
        mcp_tool: The FastMCP FunctionTool object
        user_id: Optional user_id to inject into tool calls
        description_suffix: Optional text to append to the tool's docstring.
            Used to add schema-specific context (e.g., default table for search_rem).

    Returns:
        A Pydantic AI Tool instance
    """
    # Extract the actual function from FastMCP FunctionTool
    tool_func = mcp_tool.fn

    # Check if function accepts user_id parameter
    import inspect
    sig = inspect.signature(tool_func)
    has_user_id = "user_id" in sig.parameters

    # Build the docstring with optional suffix
    base_doc = tool_func.__doc__ or ""
    final_doc = base_doc + description_suffix if description_suffix else base_doc

    # If we need to inject user_id or modify docstring, create a wrapper
    # Otherwise, use the function directly for better signature preservation
    if user_id and has_user_id:
        async def wrapped_tool(**kwargs) -> Any:
            """Wrapper that injects user_id."""
            if "user_id" not in kwargs:
                kwargs["user_id"] = user_id
                logger.debug(f"Injecting user_id={user_id} into tool {tool_name}")

            # Filter kwargs to only include parameters that the function accepts
            valid_params = set(sig.parameters.keys())
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}

            return await tool_func(**filtered_kwargs)

        # Copy signature from original function for Pydantic AI inspection
        wrapped_tool.__name__ = tool_name
        wrapped_tool.__doc__ = final_doc
        wrapped_tool.__annotations__ = tool_func.__annotations__
        wrapped_tool.__signature__ = sig  # Important: preserve full signature

        logger.debug(f"Creating MCP tool wrapper with user_id injection: {tool_name}")
        return Tool(wrapped_tool)
    elif description_suffix:
        # Need to wrap just for docstring modification
        async def wrapped_tool(**kwargs) -> Any:
            """Wrapper for docstring modification."""
            valid_params = set(sig.parameters.keys())
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}
            return await tool_func(**filtered_kwargs)

        wrapped_tool.__name__ = tool_name
        wrapped_tool.__doc__ = final_doc
        wrapped_tool.__annotations__ = tool_func.__annotations__
        wrapped_tool.__signature__ = sig

        logger.debug(f"Creating MCP tool wrapper with description suffix: {tool_name}")
        return Tool(wrapped_tool)
    else:
        # No injection needed - use original function directly
        logger.debug(f"Creating MCP tool wrapper (no injection): {tool_name}")
        return Tool(tool_func)


def create_resource_tool(uri: str, usage: str) -> Tool:
    """
    Build a Tool instance from an MCP resource URI.

    This is a placeholder for now. A real implementation would create a
    tool that reads the content of the resource URI.

    Args:
        uri: The resource URI (e.g., "rem://resources/some-id").
        usage: The description of how to use the tool.

    Returns:
        A Pydantic AI Tool instance.
    """
    # Placeholder function that would read the resource
    def read_resource():
        """Reads content from a resource URI."""
        return f"Content of {uri}"

    read_resource.__name__ = f"read_{uri.replace('://', '_').replace('/', '_')}"
    read_resource.__doc__ = usage

    logger.info(f"Built resource tool: {read_resource.__name__} (uri: {uri})")
    return Tool(read_resource)
