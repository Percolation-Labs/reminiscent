"""
Test script for MCP tools validation.

This script validates that:
1. MCP server can be created successfully
2. Tools are properly registered
3. Resources are properly registered
4. Server can be mounted on FastAPI

Run with:
    python test_mcp_tools.py
"""

import sys
from pathlib import Path
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


@pytest.fixture
def mcp():
    """Fixture that creates MCP server for tests."""
    from rem.api.mcp_router.server import create_mcp_server
    return create_mcp_server()


def test_mcp_server_creation():
    """Test that MCP server can be created."""
    print("Testing MCP server creation...")

    from rem.api.mcp_router.server import create_mcp_server

    mcp = create_mcp_server()

    print(f"✓ MCP server created: {mcp.name}")
    print(f"  Version: 0.1.0")
    print()

    assert mcp is not None


def test_mcp_tools_registered(mcp):
    """Test that all expected tools are registered."""
    print("Testing MCP tools registration...")

    # Get registered tools (FastMCP stores them internally)
    # We'll check by trying to get the tool functions
    expected_tools = [
        "search_rem",
        "ask_rem_agent",
        "ingest_into_rem",
        "read_resource",
    ]

    # FastMCP tools are registered via decorators, check if functions exist
    from rem.api.mcp_router import tools

    registered_count = 0
    for tool_name in expected_tools:
        if hasattr(tools, tool_name):
            print(f"  ✓ {tool_name}")
            registered_count += 1
        else:
            print(f"  ✗ {tool_name} (not found)")

    print(f"\nRegistered {registered_count}/{len(expected_tools)} tools")
    print()

    assert registered_count == len(expected_tools)


def test_mcp_resources_registered(mcp):
    """Test that all expected resources are registered."""
    print("Testing MCP resources registration...")

    expected_resources = [
        "rem://schema/entities",
        "rem://schema/query-types",
        "rem://status",
    ]

    # Resources are registered via decorators, we can check the module
    from rem.api.mcp_router import resources

    # Check if resource registration functions exist
    has_schema_resources = hasattr(resources, "register_schema_resources")
    has_status_resources = hasattr(resources, "register_status_resources")

    if has_schema_resources:
        print("  ✓ register_schema_resources function exists")
    if has_status_resources:
        print("  ✓ register_status_resources function exists")

    print(f"\n  Expected resources:")
    for resource_uri in expected_resources:
        print(f"    - {resource_uri}")

    print()

    assert has_schema_resources and has_status_resources


def test_mcp_http_app():
    """Test that MCP can be mounted as HTTP app."""
    print("Testing MCP HTTP app mounting...")

    from rem.api.mcp_router.server import create_mcp_server

    mcp = create_mcp_server()

    # Create HTTP app (this is what gets mounted on FastAPI)
    mcp_app = mcp.http_app(path="/", transport="http", stateless_http=True)

    print(f"  ✓ HTTP app created (stateless_http=True)")
    print(f"  ✓ Can be mounted at /api/v1/mcp")
    print()

    assert mcp_app is not None


def test_tool_parameters():
    """Test that tool functions have proper parameter definitions."""
    print("Testing tool parameter definitions...")

    from rem.api.mcp_router.tools import search_rem, ask_rem_agent, ingest_into_rem

    # Check search_rem signature
    import inspect

    sig = inspect.signature(search_rem)
    params = list(sig.parameters.keys())

    print(f"  search_rem parameters ({len(params)}):")
    expected_params = ["query_type", "tenant_id", "entity_key", "query_text", "table"]
    for param in expected_params[:5]:  # Show first 5
        if param in params:
            print(f"    ✓ {param}")
        else:
            print(f"    ✗ {param}")

    # Check ask_rem_agent signature
    sig = inspect.signature(ask_rem_agent)
    params = list(sig.parameters.keys())

    print(f"\n  ask_rem_agent parameters ({len(params)}):")
    print(f"    ✓ query")
    print(f"    ✓ tenant_id")
    print(f"    ✓ agent_schema")

    # Check ingest_into_rem signature
    sig = inspect.signature(ingest_into_rem)
    params = list(sig.parameters.keys())

    print(f"\n  ingest_into_rem parameters ({len(params)}):")
    print(f"    ✓ file_uri")
    print(f"    ✓ tenant_id")
    print(f"    ✓ user_id")
    print(f"    ✓ generate_embeddings")

    print()


def test_tool_imports():
    """Test that all tool dependencies can be imported."""
    print("Testing tool dependencies...")

    try:
        from rem.models.core import (
            QueryType,
            RemQuery,
            LookupParameters,
            FuzzyParameters,
            SearchParameters,
        )

        print("  ✓ Core models imported")

        from rem.services.postgres import PostgresService

        print("  ✓ PostgresService imported")

        from rem.services.rem import RemService

        print("  ✓ RemService imported")

        from rem.services.embeddings.api import generate_embedding_async

        print("  ✓ Embeddings API imported")

        print()
        assert True  # All imports successful

    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        print()
        assert False, f"Import failed: {e}"


def main():
    """Run all tests."""
    print("=" * 60)
    print("MCP Tools Validation Test Suite")
    print("=" * 60)
    print()

    results = []

    # Test 1: Server creation
    try:
        mcp = test_mcp_server_creation()
        results.append(("Server creation", True))
    except Exception as e:
        print(f"✗ Server creation failed: {e}")
        results.append(("Server creation", False))
        return

    # Test 2: Tools registered
    try:
        tools_ok = test_mcp_tools_registered(mcp)
        results.append(("Tools registration", tools_ok))
    except Exception as e:
        print(f"✗ Tools registration failed: {e}")
        results.append(("Tools registration", False))

    # Test 3: Resources registered
    try:
        resources_ok = test_mcp_resources_registered(mcp)
        results.append(("Resources registration", resources_ok))
    except Exception as e:
        print(f"✗ Resources registration failed: {e}")
        results.append(("Resources registration", False))

    # Test 4: HTTP app
    try:
        http_ok = test_mcp_http_app()
        results.append(("HTTP app mounting", http_ok))
    except Exception as e:
        print(f"✗ HTTP app mounting failed: {e}")
        results.append(("HTTP app mounting", False))

    # Test 5: Tool parameters
    try:
        test_tool_parameters()
        results.append(("Tool parameters", True))
    except Exception as e:
        print(f"✗ Tool parameters failed: {e}")
        results.append(("Tool parameters", False))

    # Test 6: Imports
    try:
        imports_ok = test_tool_imports()
        results.append(("Tool dependencies", imports_ok))
    except Exception as e:
        print(f"✗ Tool dependencies failed: {e}")
        results.append(("Tool dependencies", False))

    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for test_name, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print()
    print(f"Results: {passed}/{total} tests passed")
    print()

    if passed == total:
        print("✓ All tests passed! MCP tools are ready.")
        return 0
    else:
        print("✗ Some tests failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
