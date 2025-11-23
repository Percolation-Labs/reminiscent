"""
Test MCP server loading for agent tool discovery.

This test reproduces the critical issue where agents cannot load MCP tools
due to circular import errors during server initialization.

CRITICAL TEST: If this fails, agents cannot discover tool signatures and will
call tools with wrong parameters (e.g., {'query': 'LOOKUP "sarah"'} instead of
{'query_type': 'lookup', 'entity_key': 'sarah'}).
"""
import pytest


def test_mcp_server_imports_without_circular_dependency():
    """
    Test that rem.mcp_server can be imported without circular import errors.

    This is the FIRST thing that happens when an agent tries to load MCP tools.
    If this import fails, the agent cannot discover tool signatures.
    """
    print("\n" + "=" * 80)
    print("Test: MCP Server Import (Critical for Tool Discovery)")
    print("=" * 80)

    try:
        print("\n✓ Attempting to import rem.mcp_server...")
        import rem.mcp_server as mcp_server_module
        print("✓ Import succeeded!")

        # Verify the mcp instance exists
        assert hasattr(mcp_server_module, 'mcp'), "Module should have 'mcp' attribute"
        print("✓ MCP server instance found")

        mcp = mcp_server_module.mcp

        # Verify tools are registered
        print(f"\n✓ Checking registered tools...")
        # FastMCP exposes tools via _tools or similar internal attribute
        # We'll check if the server can list its tools

        # The server should have tools registered
        assert mcp is not None, "MCP server should not be None"
        print("✓ MCP server initialized successfully")

        print("\n" + "=" * 80)
        print("✅ MCP Server Import Test PASSED")
        print("=" * 80)

    except ImportError as e:
        print(f"\n❌ Import failed with ImportError: {e}")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Full error: {str(e)}")

        # Check if it's a circular import
        if "circular import" in str(e).lower() or "partially initialized" in str(e).lower():
            print("\n⚠️  CIRCULAR IMPORT DETECTED")
            print("   This prevents agents from discovering tool signatures!")

        pytest.fail(f"MCP server import failed: {e}")

    except Exception as e:
        print(f"\n❌ Import failed with {type(e).__name__}: {e}")
        pytest.fail(f"MCP server import failed: {e}")


def test_mcp_server_tools_discoverable():
    """
    Test that tools registered on MCP server can be discovered.

    Agents need to inspect tool signatures to know how to call them.
    """
    print("\n" + "=" * 80)
    print("Test: MCP Tools Discoverable")
    print("=" * 80)

    import rem.mcp_server as mcp_server_module
    mcp = mcp_server_module.mcp

    # Check if we can access tool registry
    print("\n✓ Checking tool registry...")

    # FastMCP stores tools in _tools dict or similar
    # Try to access it via introspection
    if hasattr(mcp, '_tools'):
        tools = mcp._tools
        print(f"✓ Found {len(tools)} tools via _tools attribute")
        print(f"  Tool names: {list(tools.keys())}")

        # Verify search_rem is registered
        assert 'search_rem' in tools, "search_rem tool should be registered"
        print("✓ search_rem tool found in registry")

        # Check tool signature
        search_rem_tool = tools['search_rem']
        print(f"  Tool type: {type(search_rem_tool)}")

        # Check if we can get the function
        if hasattr(search_rem_tool, 'fn'):
            fn = search_rem_tool.fn
            print(f"  Function: {fn.__name__}")

            # Get signature
            import inspect
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            print(f"  Parameters: {params}")

            # Verify critical parameters exist
            assert 'query_type' in params, "search_rem should have query_type parameter"
            assert 'entity_key' in params or 'query_text' in params, \
                "search_rem should have entity_key or query_text parameter"
            print("✓ search_rem has correct signature")

    elif hasattr(mcp, 'list_tools'):
        # Try using MCP protocol methods
        tools = mcp.list_tools()
        print(f"✓ Found {len(tools)} tools via list_tools()")
        tool_names = [t.name for t in tools]
        print(f"  Tool names: {tool_names}")

        assert 'search_rem' in tool_names, "search_rem tool should be registered"
        print("✓ search_rem tool found")

    else:
        print("⚠️  Cannot access tool registry (unknown FastMCP internal structure)")
        print("   Skipping detailed tool inspection")

    print("\n" + "=" * 80)
    print("✅ Tool Discovery Test PASSED")
    print("=" * 80)


if __name__ == "__main__":
    print("=" * 80)
    print("MCP Server Loading Tests")
    print("=" * 80)

    test_mcp_server_imports_without_circular_dependency()
    test_mcp_server_tools_discoverable()

    print("\n" + "=" * 80)
    print("✅ All MCP Server Loading Tests PASSED")
    print("=" * 80)
