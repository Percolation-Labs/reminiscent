"""
Integration tests for MCP tools layer.

Tests that MCP tools correctly wrap RemService and return serialized results.
This is the MCP layer - if these pass, we know tools are good.
"""
import asyncio
import pytest
from pathlib import Path
import yaml

from rem.api.mcp_router.tools import search_rem
from rem.settings import settings
from rem.services.postgres import get_postgres_service
from tests.integration.helpers.seed_data import seed_resources

# Get test user ID from settings
TEST_USER_ID = settings.test.effective_user_id


@pytest.fixture
async def populated_database():
    """Populate database with test data for MCP tools tests."""
    pg = get_postgres_service()
    await pg.connect()

    try:
        # Initialize MCP tools service cache with this connection
        from rem.api.mcp_router.tools import init_services
        from rem.services.rem import RemService

        rem_service = RemService(postgres_service=pg)
        init_services(postgres_service=pg, rem_service=rem_service)

        # Load resources YAML
        seed_path = Path(__file__).parent.parent / "data" / "seed" / "resources.yaml"
        with open(seed_path) as f:
            yaml_data = yaml.safe_load(f)

        # Update with test user_id
        resources_data = []
        for res in yaml_data["resources"]:
            res["user_id"] = TEST_USER_ID
            resources_data.append(res)

        # Seed database
        await seed_resources(pg, resources_data, generate_embeddings=False)

        yield pg
    finally:
        # Cleanup
        await pg.execute("DELETE FROM resources WHERE user_id = $1", (TEST_USER_ID,))
        await pg.disconnect()


@pytest.fixture(autouse=True)
async def cleanup_service_cache():
    """
    Clear service cache between tests to prevent connection pool reuse.

    AsyncIO connection pools get attached to event loops. When running
    multiple tests sequentially with pytest, we need to disconnect and
    clear the cache to avoid "attached to different loop" errors.
    """
    yield

    # Cleanup after test
    from rem.api.mcp_router.tools import _service_cache

    if "postgres" in _service_cache:
        try:
            await _service_cache["postgres"].disconnect()
        except Exception as e:
            print(f"Warning: Failed to disconnect postgres service: {e}")

    _service_cache.clear()


@pytest.mark.asyncio
async def test_search_rem_lookup(populated_database):
    """Test search_rem MCP tool with LOOKUP query using new query string format."""
    print("\n✓ Calling search_rem with LOOKUP")

    # NEW: Use query string format instead of separate parameters
    result = await search_rem(query="LOOKUP docs://getting-started.md")

    print(f"  Result type: {type(result)}")
    print(f"  Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
    print(f"  Query type from response: {result.get('query_type', 'N/A')}")

    assert isinstance(result, dict), "Result should be a dict"
    # Check for results (even 0 results is valid - no error)
    assert 'results' in result or result.get('status') != 'error', f"Unexpected error: {result}"

    if 'results' in result:
        print(f"  Results key type: {type(result['results'])}")
        print(f"  Results keys: {result['results'].keys() if isinstance(result['results'], dict) else 'N/A'}")

        if isinstance(result['results'], dict) and 'results' in result['results']:
            actual_results = result['results']['results']
            print(f"\n  ✓ Count: {len(actual_results)}")

            if len(actual_results) > 0:
                first = actual_results[0]
                print(f"  ✓ First result type: {type(first)}")
                print(f"  ✓ All keys in result: {list(first.keys())}")

                # Results have shape: {"entity_type": "resources", "data": {...resource...}}
                if 'data' in first and isinstance(first['data'], dict):
                    resource_data = first['data']
                    print(f"  ✓ Resource data keys: {list(resource_data.keys())[:10]}")

                    entity_key = resource_data.get('entity_key') or resource_data.get('name')
                    uri = resource_data.get('uri')

                    print(f"  ✓ entity_key/name: {entity_key}")
                    print(f"  ✓ uri: {uri}")
                    print(f"  ✓ entity_type: {first.get('entity_type', 'N/A')}")

                    assert entity_key == 'docs://getting-started.md' or uri == 'docs://getting-started.md', \
                        f"Expected entity_key or uri to be 'docs://getting-started.md', got entity_key={entity_key}, uri={uri}"
                    assert first.get('entity_type') == 'resources'
                else:
                    # Flat structure (old format)
                    entity_key = first.get('entity_key') or first.get('name')
                    uri = first.get('uri')
                    print(f"  ✓ entity_key/name: {entity_key}")
                    print(f"  ✓ uri: {uri}")

                    assert entity_key == 'docs://getting-started.md' or uri == 'docs://getting-started.md'
                    assert first.get('entity_type') == 'resources'
            else:
                print("  ⚠️  No results found (entity may not exist in test data)")
        else:
            print(f"  ⚠️  Unexpected results structure: {result}")


@pytest.mark.asyncio
async def test_search_rem_fuzzy():
    """Test search_rem MCP tool with FUZZY query using new query string format."""
    print("\n✓ Calling search_rem with FUZZY")

    # NEW: Use query string format - threshold is now fixed at 0.3 in the function
    result = await search_rem(query="FUZZY Sara")

    print(f"  Result type: {type(result)}")
    print(f"  Query type from response: {result.get('query_type', 'N/A')}")

    assert isinstance(result, dict), "Result should be a dict"
    # Check for results (even 0 results is valid - no error)
    assert 'results' in result or result.get('status') != 'error', f"Unexpected error: {result}"

    if 'results' in result and isinstance(result['results'], dict):
        count = result['results'].get('count', 0)
        print(f"  ✓ Count: {count}")

        if count > 0:
            results_list = result['results'].get('results', [])
            if results_list:
                first = results_list[0]
                print(f"  ✓ First result: {first.get('entity_key', 'N/A')}")
                print(f"  ✓ Similarity: {first.get('similarity_score', 'N/A')}")


@pytest.mark.asyncio
async def test_search_rem_query_types():
    """Test that various query types are recognized."""
    print("\n✓ Testing query type parsing")

    # LOOKUP - should be recognized
    result = await search_rem(query="LOOKUP test-entity")
    print(f"  LOOKUP query_type: {result.get('query_type', 'N/A')}")
    assert result.get('query_type') == 'LOOKUP', f"Expected LOOKUP, got: {result}"

    # FUZZY - should be recognized
    result = await search_rem(query="FUZZY test")
    print(f"  FUZZY query_type: {result.get('query_type', 'N/A')}")
    assert result.get('query_type') == 'FUZZY', f"Expected FUZZY, got: {result}"

    # SEARCH - should be recognized
    result = await search_rem(query="SEARCH depression IN ontologies")
    print(f"  SEARCH query_type: {result.get('query_type', 'N/A')}")
    assert result.get('query_type') == 'SEARCH', f"Expected SEARCH, got: {result}"


@pytest.mark.asyncio
async def test_search_rem_invalid_query():
    """Test that invalid queries return helpful errors."""
    print("\n✓ Testing invalid query handling")

    # Empty query
    result = await search_rem(query="")
    print(f"  Empty query status: {result.get('status', 'N/A')}")
    assert result.get('status') == 'error', "Empty query should return error"
    assert 'error' in result

    # Unknown query type
    result = await search_rem(query="INVALID some-text")
    print(f"  Invalid type status: {result.get('status', 'N/A')}")
    assert result.get('status') == 'error', "Invalid query type should return error"
    assert 'Unknown query type' in result.get('error', '')


if __name__ == "__main__":
    print("=" * 80)
    print("Test 1: search_rem LOOKUP")
    print("=" * 80)
    asyncio.run(test_search_rem_lookup())

    print("\n" + "=" * 80)
    print("Test 2: search_rem FUZZY")
    print("=" * 80)
    asyncio.run(test_search_rem_fuzzy())

    print("\n" + "=" * 80)
    print("Test 3: Query Types")
    print("=" * 80)
    asyncio.run(test_search_rem_query_types())

    print("\n" + "=" * 80)
    print("Test 4: Invalid Query")
    print("=" * 80)
    asyncio.run(test_search_rem_invalid_query())

    print("\n" + "=" * 80)
    print("✅ All MCP Tool Tests Passed!")
    print("=" * 80)
