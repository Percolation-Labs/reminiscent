"""
End-to-end test for embeddings and SEARCH functionality.

This test demonstrates the full embedding workflow:
1. Insert documents with embedding generation enabled
2. Background worker generates embeddings via OpenAI API
3. SEARCH query generates embedding and finds similar documents

Requires:
- Running PostgreSQL (docker compose up -d postgres)
- OPENAI_API_KEY environment variable (optional - will use zero vectors if missing)
"""

import asyncio
import os
from pathlib import Path

import pytest
import yaml
from datetime import datetime

from rem.models.entities import Resource
from rem.services.postgres import PostgresService
from rem.services.rem.query import REMQueryService
from rem.services.embeddings import EmbeddingWorker


@pytest.fixture
def seed_data_path() -> Path:
    """Path to seed data directory."""
    return Path(__file__).parent.parent / "data" / "seed"


@pytest.fixture
def resources_seed_data(seed_data_path: Path) -> list[dict]:
    """Load resources seed data from YAML."""
    yaml_file = seed_data_path / "resources.yaml"
    with open(yaml_file) as f:
        data = yaml.safe_load(f)
    return data.get("resources", [])


@pytest.fixture
async def postgres_service() -> PostgresService:
    """Create PostgresService instance."""
    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def embedding_worker(postgres_service) -> EmbeddingWorker:
    """Create and start EmbeddingWorker with OpenAI integration."""
    api_key = os.getenv("OPENAI_API_KEY")

    worker = EmbeddingWorker(
        postgres_service=postgres_service,
        num_workers=2,
        batch_size=5,
        batch_timeout=0.5,
        openai_api_key=api_key,
    )
    await worker.start()
    yield worker
    await worker.stop()


@pytest.fixture
async def rem_query_service(postgres_service) -> REMQueryService:
    """Create REMQueryService instance."""
    return REMQueryService(postgres_service)


@pytest.mark.asyncio
async def test_embeddings_e2e_workflow(
    postgres_service, embedding_worker, rem_query_service, resources_seed_data
):
    """
    Test end-to-end embedding workflow with SEARCH.

    Flow:
    1. Attach embedding worker to postgres service
    2. Insert resources with generate_embeddings=True
    3. Worker processes embedding tasks in background
    4. Verify embeddings are created in database
    5. Execute SEARCH query with real embedding
    6. Verify search returns relevant results
    """
    # Attach worker to postgres service
    postgres_service.embedding_worker = embedding_worker

    # Convert YAML to Resource models (use first 3 for faster test)
    resources = []
    for data in resources_seed_data[:3]:
        if "ordinal" not in data:
            data["ordinal"] = 0
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(
                data["timestamp"].replace("Z", "+00:00")
            ).replace(tzinfo=None)
        resource = Resource(**data)
        resources.append(resource)

    # Batch upsert using Repository pattern with embedding generation
    from rem.services.postgres import Repository
    repo = Repository(Resource, "resources", db=postgres_service)
    upserted = await repo.upsert(
        resources,
        embeddable_fields=["content"],
        generate_embeddings=True
    )

    # Verify resources were upserted
    assert len(upserted) == 3

    # Wait for worker to process embedding tasks
    print("\nWaiting for background embedding generation...")
    await asyncio.sleep(3)

    # Check if embeddings were created for our specific resources
    resource_ids = [str(r.id) for r in resources]
    embeddings = await postgres_service.fetch(
        """
        SELECT entity_id, field_name, provider, model,
               vector_dims(embedding) as dims
        FROM embeddings_resources
        WHERE entity_id = ANY($1::uuid[])
        ORDER BY created_at
        """,
        resource_ids
    )

    if os.getenv("OPENAI_API_KEY"):
        # With API key: should have real embeddings
        print(f"\n✓ Generated {len(embeddings)} embeddings via OpenAI API")
        assert len(embeddings) == 3
        for emb in embeddings:
            assert emb["field_name"] == "content"
            assert emb["provider"] == "openai"
            assert emb["model"] == "text-embedding-3-small"
            assert emb["dims"] == 1536
    else:
        # Without API key: will have zero-vector embeddings
        print(f"\n⚠ Generated {len(embeddings)} zero-vector embeddings (no API key)")
        assert len(embeddings) == 3
        for emb in embeddings:
            assert emb["dims"] == 1536

    # Now test SEARCH query
    print("\nExecuting SEARCH query...")
    search_result = await rem_query_service.execute(
        'SEARCH "getting started with REM" FROM resources LIMIT 5',
        user_id="acme-corp",
    )

    print(f"Search returned {search_result.count} results")

    # Verify search executed successfully
    assert search_result.operation == "SEARCH"
    assert search_result.metadata["search_text"] == "getting started with REM"
    assert search_result.metadata["table"] == "resources"
    assert search_result.metadata["limit"] == 5

    if os.getenv("OPENAI_API_KEY"):
        # With API key: should find relevant documents
        print(f"✓ SEARCH found {search_result.count} relevant documents")
        assert search_result.count >= 1  # Should find at least the getting-started doc

        # Check that results have distance metric (0 = perfect match, 1 = different)
        for result in search_result.results:
            assert "entity_key" in result
            assert "distance" in result
            print(
                f"  - {result['entity_key']}: distance={result['distance']:.3f}"
            )
    else:
        # Without API key: zero vectors won't match anything meaningfully
        print("⚠ SEARCH results may be limited (zero-vector embeddings)")
        # Just verify it didn't error
        assert search_result.count >= 0


@pytest.mark.asyncio
async def test_search_without_embeddings(postgres_service, rem_query_service):
    """
    Test that SEARCH gracefully handles missing embeddings.

    When no embeddings exist in the database, SEARCH should return
    empty results without errors.
    """
    # Clear any existing embeddings
    await postgres_service.execute("TRUNCATE embeddings_resources CASCADE")

    # Execute SEARCH on empty embeddings table
    result = await rem_query_service.execute(
        'SEARCH "test query" FROM resources LIMIT 5',
        user_id="acme-corp",
    )

    # Should return no results but not error
    assert result.operation == "SEARCH"
    assert result.count == 0
    assert result.results == []


if __name__ == "__main__":
    """
    Run embeddings end-to-end test manually.

    Usage:
        # With OpenAI API key (generates real embeddings)
        export OPENAI_API_KEY=sk-...
        python -m tests.integration.test_embeddings_e2e

        # Without API key (uses zero vectors)
        python -m tests.integration.test_embeddings_e2e
    """
    print("=" * 70)
    print("REM Embeddings End-to-End Test")
    print("=" * 70)

    if os.getenv("OPENAI_API_KEY"):
        print("\n✓ OPENAI_API_KEY is set - will generate real embeddings")
    else:
        print("\n⚠ OPENAI_API_KEY not set - will use zero-vector embeddings")
        print("  Set OPENAI_API_KEY environment variable for real embeddings")

    print("\nNote: Requires PostgreSQL running (docker compose up -d postgres)")
    print("\nTo run with pytest:")
    print("  pytest tests/integration/test_embeddings_e2e.py -v -s")
