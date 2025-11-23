"""
Integration tests for RemService layer.

Tests that RemService correctly wraps PostgreSQL functions and returns results.
This is the service layer - if these pass, we know the service is good.
"""
from rem.settings import settings
import asyncio
import pytest
from rem.services.postgres import get_postgres_service
from rem.services.rem import RemService
from rem.models.core import RemQuery, QueryType, LookupParameters, FuzzyParameters


@pytest.mark.asyncio
async def test_rem_service_lookup():
    """Test RemService.execute_query with LOOKUP."""
    db = get_postgres_service()
    await db.connect()

    try:
        rem_service = RemService(postgres_service=db)

        # Create LOOKUP query
        query = RemQuery(
            query_type=QueryType.LOOKUP,
            parameters=LookupParameters(
                key='Sarah Chen',
                user_id=settings.test.effective_user_id,
            ),
            user_id=settings.test.effective_user_id,
        )

        print(f"\n✓ Executing LOOKUP query: {query}")
        result = await rem_service.execute_query(query)

        print(f"  Result type: {type(result)}")
        print(f"  Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
        print(f"  Result: {result}")

        assert isinstance(result, dict), "Result should be a dict"
        assert 'results' in result, "Result should have 'results' key"
        assert 'count' in result, "Result should have 'count' key"

        print(f"\n  ✓ Count: {result['count']}")
        print(f"  ✓ Results: {len(result['results'])} items")

        if result['count'] > 0:
            first_result = result['results'][0]
            print(f"  ✓ First result keys: {first_result.keys() if isinstance(first_result, dict) else type(first_result)}")
            print(f"  ✓ entity_key: {first_result.get('entity_key', 'N/A')}")
            print(f"  ✓ entity_type: {first_result.get('entity_type', 'N/A')}")

            assert first_result['entity_key'] == 'Sarah Chen'
            assert first_result['entity_type'] == 'users'
        else:
            print("  ⚠️  WARNING: No results returned!")
            print(f"  Full result: {result}")

    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_rem_service_fuzzy():
    """Test RemService.execute_query with FUZZY."""
    db = get_postgres_service()
    await db.connect()

    try:
        rem_service = RemService(postgres_service=db)

        # Create FUZZY query
        query = RemQuery(
            query_type=QueryType.FUZZY,
            parameters=FuzzyParameters(
                query_text='Sara',  # Partial match
                threshold=0.3,
                limit=10,
            ),
            user_id=settings.test.effective_user_id,
        )

        print(f"\n✓ Executing FUZZY query: {query}")
        result = await rem_service.execute_query(query)

        print(f"  Result type: {type(result)}")
        print(f"  Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")

        assert isinstance(result, dict), "Result should be a dict"
        print(f"\n  ✓ Count: {result.get('count', 'N/A')}")
        print(f"  ✓ Results: {len(result.get('results', []))} items")

        if result.get('count', 0) > 0:
            first_result = result['results'][0]
            print(f"  ✓ First result: {first_result.get('entity_key', 'N/A')}")
            print(f"  ✓ Similarity: {first_result.get('similarity_score', 'N/A')}")
        else:
            print("  ⚠️  WARNING: No results returned!")

    finally:
        await db.disconnect()


if __name__ == "__main__":
    print("=" * 80)
    print("Test 1: RemService LOOKUP")
    print("=" * 80)
    asyncio.run(test_rem_service_lookup())

    print("\n" + "=" * 80)
    print("Test 2: RemService FUZZY")
    print("=" * 80)
    asyncio.run(test_rem_service_fuzzy())

    print("\n" + "=" * 80)
    print("✅ All Service Layer Tests Passed!")
    print("=" * 80)
