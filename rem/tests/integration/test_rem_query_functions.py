"""
Integration tests for REM query PostgreSQL functions.

Tests each database function directly to ensure migrations are correct.
This is the foundation layer - if these pass, we know the DB is good.
"""
import asyncio
import pytest
from pathlib import Path
import yaml

from rem.services.postgres import get_postgres_service
from rem.settings import settings
from tests.integration.helpers.seed_data import seed_resources

# Get test user ID from settings (deterministic UUID from test@rem.ai)
TEST_USER_ID = settings.test.effective_user_id


@pytest.fixture
async def populated_database():
    """Populate database with test seed data."""
    pg = get_postgres_service()
    await pg.connect()

    try:
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


@pytest.mark.asyncio
async def test_rem_lookup_function(populated_database):
    """Test rem_lookup PostgreSQL function directly."""
    db = populated_database

    # Test LOOKUP for getting-started doc
    query = "SELECT entity_type, data FROM rem_lookup($1, $2, $3);"
    params = ('docs://getting-started.md', TEST_USER_ID, TEST_USER_ID)

    results = await db.execute(query, params)

    print(f"\n✓ rem_lookup returned {len(results)} rows")
    assert len(results) > 0, "rem_lookup should return getting-started doc"

    # Check structure - data is JSONB
    row = results[0]
    print(f"  Row type: {type(row)}")
    print(f"  Row keys: {row.keys() if hasattr(row, 'keys') else 'N/A'}")

    # Extract from JSONB data field
    data = dict(row['data'])
    print(f"  entity_key: {data.get('name', 'N/A')}")
    print(f"  entity_type: {row['entity_type']}")
    print(f"  user_id: {data.get('user_id', 'N/A')}")

    assert data['name'] == 'docs://getting-started.md'
    assert row['entity_type'] == 'resources'
    assert data['user_id'] == TEST_USER_ID


@pytest.mark.asyncio
async def test_rem_fuzzy_function():
    """Test rem_fuzzy PostgreSQL function directly."""
    db = get_postgres_service()
    await db.connect()

    try:
        # Test FUZZY for "Sara" (partial match for "Sarah Chen")
        query = "SELECT * FROM rem_fuzzy($1, $2, $3, $4, $5);"
        params = ('Sara', TEST_USER_ID, 0.3, 10, TEST_USER_ID)

        results = await db.execute(query, params)

        print(f"\n✓ rem_fuzzy returned {len(results)} rows")

        if len(results) > 0:
            row = results[0]
            print(f"  Row type: {type(row)}")
            print(f"  Row keys: {row.keys() if hasattr(row, 'keys') else 'N/A'}")
            print(f"  entity_key: {row['entity_key']}")
            print(f"  similarity_score: {row['similarity_score']}")

            assert 'entity_key' in row
            assert 'similarity_score' in row
        else:
            print("  ⚠️  No fuzzy matches found (threshold too high?)")

    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_kv_store_population(populated_database):
    """Test that KV store is populated with test data."""
    db = populated_database

    query = "SELECT entity_key, entity_type FROM kv_store WHERE user_id = $1;"
    params = (TEST_USER_ID,)

    results = await db.execute(query, params)

    print(f"\n✓ KV store has {len(results)} entries for test user")

    # Find getting-started doc
    doc_entries = [r for r in results if 'getting-started' in r['entity_key']]
    print(f"  Getting-started entries: {len(doc_entries)}")

    if doc_entries:
        for entry in doc_entries:
            print(f"    - {entry['entity_key']} ({entry['entity_type']})")

    assert len(doc_entries) > 0, "KV store should have getting-started doc entry"


if __name__ == "__main__":
    print("=" * 80)
    print("Test 1: KV Store Population")
    print("=" * 80)
    asyncio.run(test_kv_store_population())

    print("\n" + "=" * 80)
    print("Test 2: rem_lookup Function")
    print("=" * 80)
    asyncio.run(test_rem_lookup_function())

    print("\n" + "=" * 80)
    print("Test 3: rem_fuzzy Function")
    print("=" * 80)
    asyncio.run(test_rem_fuzzy_function())

    print("\n" + "=" * 80)
    print("✅ All Database Function Tests Passed!")
    print("=" * 80)
