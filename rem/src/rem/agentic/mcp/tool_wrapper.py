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


def create_resource_tool(uri: str, usage: str = "", mcp_server: Any = None) -> Tool:
    """
    Build a Tool instance from an MCP resource URI.

    Creates a tool that fetches the resource content when called.
    Resources declared in agent YAML become callable tools - this eliminates
    the artificial MCP distinction between tools and resources.

    Supports both:
    - Concrete URIs: "rem://agents" -> tool with no parameters
    - Template URIs: "patient-profile://field/{field_key}" -> tool with field_key parameter

    Args:
        uri: The resource URI (concrete or template with {variable} placeholders).
        usage: The description of what this resource provides.
        mcp_server: Optional FastMCP server instance to resolve resources from.
            If provided, resources are resolved from this server's registry.
            If not provided, falls back to REM's built-in load_resource().

    Returns:
        A Pydantic AI Tool instance that fetches the resource.

    Example:
        # Concrete URI -> no-param tool
        tool = create_resource_tool("rem://agents", "List all agent schemas")

        # Template URI -> parameterized tool
        tool = create_resource_tool("patient-profile://field/{field_key}", "Get field definition", mcp_server=mcp)
        # Agent calls: get_patient_profile_field(field_key="safety.suicidality")
    """
    import json
    import re

    # Extract template variables from URI (e.g., {field_key}, {domain_name})
    template_vars = re.findall(r'\{([^}]+)\}', uri)

    # Parse URI to create function name (strip template vars for cleaner name)
    clean_uri = re.sub(r'\{[^}]+\}', '', uri)
    parts = clean_uri.replace("://", "_").replace("-", "_").replace("/", "_").replace(".", "_")
    parts = re.sub(r'_+', '_', parts).strip('_')  # Clean up multiple underscores
    func_name = f"get_{parts}"

    # For parameterized URIs, append _by_{params} to avoid naming conflicts
    # e.g., rem://agents/{name} -> get_rem_agents_by_name (distinct from get_rem_agents)
    if template_vars:
        param_suffix = "_by_" + "_".join(template_vars)
        func_name = f"{func_name}{param_suffix}"

    # Build description including parameter info
    description = usage or f"Fetch {uri} resource"
    if template_vars:
        param_desc = ", ".join(template_vars)
        description = f"{description}\n\nParameters: {param_desc}"

    # Capture mcp_server reference at tool creation time (for closure)
    # This ensures the correct server is used even if called later
    _captured_mcp_server = mcp_server
    _captured_uri = uri  # Also capture URI for consistent logging

    if template_vars:
        # Template URI -> create parameterized tool
        async def wrapper(**kwargs: Any) -> str:
            """Fetch MCP resource with substituted parameters."""
            import asyncio
            import inspect

            logger.debug(f"Resource tool invoked: uri={_captured_uri}, kwargs={kwargs}, mcp_server={'set' if _captured_mcp_server else 'None'}")

            # Try to resolve from MCP server's resource templates first
            if _captured_mcp_server is not None:
                try:
                    # Get resource templates from MCP server
                    templates = await _captured_mcp_server.get_resource_templates()
                    logger.debug(f"MCP server templates: {list(templates.keys())}")
                    if _captured_uri in templates:
                        template = templates[_captured_uri]
                        logger.debug(f"Found template for {_captured_uri}, calling fn with kwargs={kwargs}")
                        # Call the template's underlying function directly
                        # The fn expects the template variables as kwargs
                        fn_result = template.fn(**kwargs)
                        # Handle both sync and async functions
                        if inspect.iscoroutine(fn_result):
                            fn_result = await fn_result
                        if isinstance(fn_result, str):
                            return fn_result
                        return json.dumps(fn_result, indent=2)
                    else:
                        logger.warning(f"Template {_captured_uri} not found in MCP server templates: {list(templates.keys())}")
                except Exception as e:
                    logger.warning(f"Failed to resolve resource {_captured_uri} from MCP server: {e}", exc_info=True)
            else:
                logger.warning(f"No MCP server provided for resource tool {_captured_uri}, using fallback")

            # Fallback: substitute template variables and use load_resource
            resolved_uri = _captured_uri
            for var in template_vars:
                if var in kwargs:
                    resolved_uri = resolved_uri.replace(f"{{{var}}}", str(kwargs[var]))
                else:
                    return json.dumps({"error": f"Missing required parameter: {var}"})

            logger.debug(f"Using fallback load_resource for resolved URI: {resolved_uri}")
            from rem.api.mcp_router.resources import load_resource
            result = await load_resource(resolved_uri)
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2)

        # Build parameter annotations for Pydantic AI
        wrapper.__name__ = func_name
        wrapper.__doc__ = description
        # Add type hints for parameters
        wrapper.__annotations__ = {var: str for var in template_vars}
        wrapper.__annotations__['return'] = str

        logger.info(f"Built parameterized resource tool: {func_name} (uri: {uri}, params: {template_vars}, mcp_server={'provided' if mcp_server else 'None'})")
    else:
        # Concrete URI -> no-param tool
        async def wrapper(**kwargs: Any) -> str:
            """Fetch MCP resource and return contents."""
            import asyncio
            import inspect

            if kwargs:
                logger.warning(f"Resource tool {func_name} called with unexpected kwargs: {list(kwargs.keys())}")

            logger.debug(f"Concrete resource tool invoked: uri={_captured_uri}, mcp_server={'set' if _captured_mcp_server else 'None'}")

            # Try to resolve from MCP server's resources first
            if _captured_mcp_server is not None:
                try:
                    resources = await _captured_mcp_server.get_resources()
                    logger.debug(f"MCP server resources: {list(resources.keys())}")
                    if _captured_uri in resources:
                        resource = resources[_captured_uri]
                        logger.debug(f"Found resource for {_captured_uri}")
                        # Call the resource's underlying function
                        fn_result = resource.fn()
                        if inspect.iscoroutine(fn_result):
                            fn_result = await fn_result
                        if isinstance(fn_result, str):
                            return fn_result
                        return json.dumps(fn_result, indent=2)
                    else:
                        logger.warning(f"Resource {_captured_uri} not found in MCP server resources: {list(resources.keys())}")
                except Exception as e:
                    logger.warning(f"Failed to resolve resource {_captured_uri} from MCP server: {e}", exc_info=True)
            else:
                logger.warning(f"No MCP server provided for resource tool {_captured_uri}, using fallback")

            # Fallback to load_resource
            logger.debug(f"Using fallback load_resource for URI: {_captured_uri}")
            from rem.api.mcp_router.resources import load_resource
            result = await load_resource(_captured_uri)
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2)

        wrapper.__name__ = func_name
        wrapper.__doc__ = description

        logger.info(f"Built resource tool: {func_name} (uri: {uri}, mcp_server={'provided' if mcp_server else 'None'})")

    return Tool(wrapper)
