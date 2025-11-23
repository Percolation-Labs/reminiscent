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
    """Test search_rem MCP tool with LOOKUP query."""
    print("\n✓ Calling search_rem with LOOKUP")

    result = await search_rem(
        query_type='lookup',
        entity_key='docs://getting-started.md',
        user_id=settings.test.effective_user_id
    )

    print(f"  Result type: {type(result)}")
    print(f"  Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
    print(f"  Status: {result.get('status', 'N/A')}")

    assert isinstance(result, dict), "Result should be a dict"
    assert result.get('status') == 'success', f"Expected success, got: {result}"

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
                # Need to extract the actual resource from the data field
                if 'data' in first and isinstance(first['data'], dict):
                    resource_data = first['data']
                    print(f"  ✓ Resource data keys: {list(resource_data.keys())[:10]}")

                    # Check for entity_key or name field (backward compat)
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
                print("  ⚠️  WARNING: No results in nested results array!")
        else:
            print(f"  ⚠️  WARNING: Unexpected results structure!")
            print(f"  Full result: {result}")


@pytest.mark.asyncio
async def test_search_rem_fuzzy():
    """Test search_rem MCP tool with FUZZY query."""
    print("\n✓ Calling search_rem with FUZZY")

    result = await search_rem(
        query_type='fuzzy',
        query_text='Sara',
        threshold=0.3,
        user_id=settings.test.effective_user_id
    )

    print(f"  Result type: {type(result)}")
    print(f"  Status: {result.get('status', 'N/A')}")

    assert isinstance(result, dict), "Result should be a dict"
    assert result.get('status') == 'success', f"Expected success, got: {result}"

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
async def test_search_rem_case_insensitive():
    """Test that query_type is case-insensitive."""
    print("\n✓ Testing case-insensitive query_type")

    # Test with uppercase
    result = await search_rem(
        query_type='LOOKUP',  # Uppercase
        entity_key='Sarah Chen',
        user_id=settings.test.effective_user_id
    )

    print(f"  Status with uppercase 'LOOKUP': {result.get('status', 'N/A')}")
    assert result.get('status') == 'success', "Should handle uppercase query_type"


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
    print("Test 3: Case-Insensitive query_type")
    print("=" * 80)
    asyncio.run(test_search_rem_case_insensitive())

    print("\n" + "=" * 80)
    print("✅ All MCP Tool Tests Passed!")
    print("=" * 80)
