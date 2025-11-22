"""
MCP Tool Wrappers for Pydantic AI.

This module provides functions to convert MCP tool functions and resources
into a format compatible with the Pydantic AI library.
"""

from loguru import logger
from pydantic_ai.tools import Tool


def create_pydantic_tool(func: callable) -> Tool:
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
