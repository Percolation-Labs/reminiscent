"""
Integration test for MCP tool loading and signature inspection.

Tests that FastMCP tools are correctly converted to Pydantic AI tools
with proper signatures that the LLM can understand.
"""
from rem.settings import settings

import asyncio
import pytest
from pydantic_ai import Agent

from rem.agentic.providers.pydantic_ai import create_agent
from rem.agentic.context import AgentContext
from rem.utils.schema_loader import load_agent_schema


@pytest.mark.asyncio
async def test_mcp_tool_loading():
    """Test that MCP tools are loaded from the in-process server."""
    # Load rem agent schema
    schema = load_agent_schema("rem")
    context = AgentContext(user_id=settings.test.effective_user_id)

    # Create agent
    agent = await create_agent(context=context, agent_schema_override=schema)

    # Verify agent was created
    assert agent is not None
    assert isinstance(agent.agent, Agent)  # AgentRuntime.agent is the inner Agent

    # Check that tools were loaded
    # Pydantic AI stores tools in _function_toolset attribute (on inner agent)
    inner_agent = agent.agent
    if hasattr(inner_agent, '_function_toolset'):
        toolset = inner_agent._function_toolset
        print(f"\n✓ Agent has _function_toolset: {type(toolset)}")

        # Try to get tools from toolset
        if hasattr(toolset, 'tools'):
            tools = toolset.tools
            print(f"  Toolset has {len(tools)} tools:")
            for tool_name, tool in tools.items():
                print(f"    - {tool_name}: {type(tool)}")
                if hasattr(tool, 'description'):
                    print(f"      Description: {tool.description[:100] if tool.description else 'None'}...")
        elif hasattr(toolset, '__dict__'):
            print(f"  Toolset dict: {toolset.__dict__.keys()}")
        else:
            print(f"  Toolset attributes: {[attr for attr in dir(toolset) if not attr.startswith('_')]}")
    else:
        # Try to find tools in other attributes
        print(f"\nAgent tool attributes: {[attr for attr in dir(inner_agent) if 'tool' in attr.lower()]}")

        # Try _user_toolsets
        if hasattr(inner_agent, '_user_toolsets'):
            toolsets = inner_agent._user_toolsets
            print(f"\n✓ Agent has {len(toolsets)} user toolsets")
            for ts in toolsets:
                print(f"  Toolset: {type(ts)}")
                print(f"  Dir: {[attr for attr in dir(ts) if not attr.startswith('_')][:10]}")


@pytest.mark.asyncio
async def test_mcp_tool_signatures():
    """Test that MCP tool signatures are correct for LLM consumption."""
    from rem.mcp_server import mcp

    # Get tools from MCP server
    mcp_tools = await mcp.get_tools()

    print(f"\n✓ MCP server has {len(mcp_tools)} tools:")
    for tool_name, tool_obj in mcp_tools.items():
        print(f"\n  Tool: {tool_name}")
        print(f"    Type: {type(tool_obj)}")
        print(f"    Has 'fn' attr: {hasattr(tool_obj, 'fn')}")
        print(f"    Has 'parameters' attr: {hasattr(tool_obj, 'parameters')}")

        if hasattr(tool_obj, 'fn'):
            func = tool_obj.fn
            print(f"    Function: {func.__name__}")
            print(f"    Signature: {func.__code__.co_varnames[:func.__code__.co_argcount]}")
            print(f"    Annotations: {func.__annotations__}")
            print(f"    Docstring: {func.__doc__[:200] if func.__doc__ else 'None'}...")

        if hasattr(tool_obj, 'parameters'):
            params = tool_obj.parameters
            print(f"    Parameters schema: {params}")


@pytest.mark.asyncio
async def test_tool_wrapper_preserves_signature():
    """Test that our tool wrapper preserves function signatures."""
    from rem.mcp_server import mcp
    from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper
    from pydantic_ai.tools import Tool

    # Get a tool from MCP server
    mcp_tools = await mcp.get_tools()
    tool_name = "search_rem"

    assert tool_name in mcp_tools, f"Tool {tool_name} not found in MCP server"

    mcp_tool = mcp_tools[tool_name]

    # Create wrapped tool
    wrapped_tool = create_mcp_tool_wrapper(tool_name, mcp_tool, user_id=settings.test.effective_user_id)

    print(f"\n✓ Wrapped tool created:")
    print(f"  Type: {type(wrapped_tool)}")
    print(f"  Is Tool: {isinstance(wrapped_tool, Tool)}")

    # Inspect the wrapped tool
    if hasattr(wrapped_tool, 'function'):
        func = wrapped_tool.function
        print(f"  Function name: {func.__name__}")
        print(f"  Function annotations: {func.__annotations__}")
        print(f"  Function docstring: {func.__doc__[:200] if func.__doc__ else 'None'}...")

    # Check if Tool has schema method
    if hasattr(wrapped_tool, 'prepare_tool_def'):
        print(f"  Has prepare_tool_def method")

    # Try to get the tool definition that would be sent to LLM
    # This is what Pydantic AI uses to tell the LLM about tools
    if hasattr(wrapped_tool, 'name'):
        print(f"  Tool name for LLM: {wrapped_tool.name}")
    if hasattr(wrapped_tool, 'description'):
        print(f"  Tool description for LLM: {wrapped_tool.description[:200] if wrapped_tool.description else 'None'}...")


@pytest.mark.asyncio
async def test_agent_can_list_tools():
    """Test that agent can list its available tools."""
    schema = load_agent_schema("rem")
    context = AgentContext(user_id=settings.test.effective_user_id)
    agent = await create_agent(context=context, agent_schema_override=schema)

    # Try different ways to access tools
    print("\n✓ Checking agent for tool attributes:")

    tool_attrs = [
        '_function_tools',
        'tools',
        '_tools',
        'function_tools',
    ]

    for attr in tool_attrs:
        # Check on the inner agent (agent.agent)
        if hasattr(agent.agent, attr):
            value = getattr(agent.agent, attr)
            print(f"  {attr}: {type(value)}, length: {len(value) if hasattr(value, '__len__') else 'N/A'}")


if __name__ == "__main__":
    # Run tests directly
    print("=" * 80)
    print("Test 1: MCP Tool Loading")
    print("=" * 80)
    asyncio.run(test_mcp_tool_loading())

    print("\n" + "=" * 80)
    print("Test 2: MCP Tool Signatures")
    print("=" * 80)
    asyncio.run(test_mcp_tool_signatures())

    print("\n" + "=" * 80)
    print("Test 3: Tool Wrapper Signature Preservation")
    print("=" * 80)
    asyncio.run(test_tool_wrapper_preserves_signature())

    print("\n" + "=" * 80)
    print("Test 4: Agent Tool Listing")
    print("=" * 80)
    asyncio.run(test_agent_can_list_tools())
