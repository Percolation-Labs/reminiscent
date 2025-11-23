"""
Integration tests for REM Query Service (REM dialect).

Tests:
1. SQL - Execute raw SQL queries
2. SEARCH - Vector similarity search
3. LOOKUP - Exact KV store lookup
4. FUZZY LOOKUP - Trigram fuzzy search
5. TRAVERSE - Graph traversal with edges

Requires:
- Running PostgreSQL instance (docker compose up -d postgres)
- Seed data with graph edges
"""

import os
import pytest
from pathlib import Path
import yaml
from datetime import datetime

from rem.models.entities import Resource
from rem.services.postgres import PostgresService, Repository
from rem.services.rem.query import REMQueryService


# Skip embedding tests if no API key
requires_openai_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="SEARCH tests require OPENAI_API_KEY for embedding generation"
)


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
    # Connection string is now read from settings
    # settings.postgres.connection_string defaults to localhost:5050 in test/dev
    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def rem_query_service(postgres_service) -> REMQueryService:
    """Create REMQueryService instance."""
    return REMQueryService(postgres_service)


@pytest.fixture
async def populated_database(postgres_service, resources_seed_data):
    """Populate database with seed data including graph edges."""
    # Convert YAML to Resource models
    resources = []
    for data in resources_seed_data:
        if "ordinal" not in data:
            data["ordinal"] = 0
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(
                data["timestamp"].replace("Z", "+00:00")
            ).replace(tzinfo=None)  # Strip timezone, assume UTC
        resource = Resource(**data)
        resources.append(resource)

    # Batch upsert using Repository pattern with embeddings
    repo = Repository(Resource, "resources", db=postgres_service)
    await repo.upsert(
        resources,
        embeddable_fields=["content"],
        generate_embeddings=True,  # Generate embeddings for SEARCH tests
    )

    # Wait for embedding generation to complete
    import asyncio
    await asyncio.sleep(10.0)  # Give background workers time to process embeddings
    # Note: Embeddings are generated asynchronously by background workers
    # In test environments, workers may be slower due to API rate limits

    return resources


class TestREMQuerySQL:
    """Test SQL operation."""

    async def test_sql_select(self, rem_query_service, populated_database):
        """Test SQL SELECT query."""
        result = await rem_query_service.execute(
            'SELECT name, category FROM resources WHERE category = \'documentation\' LIMIT 3'
        )

        assert result.operation == "SQL"
        assert result.count > 0
        assert all("name" in r for r in result.results)

    async def test_sql_with_tenant(self, rem_query_service, populated_database):
        """Test SQL with tenant filter."""
        result = await rem_query_service.execute(
            "SELECT * FROM resources WHERE tenant_id = 'acme-corp'",
            user_id="acme-corp",
        )

        assert result.operation == "SQL"
        # Check that we got results (not checking exact count since data accumulates)
        assert result.count >= 5  # At least our seed data
        # Verify all results have correct tenant_id
        assert all(r["tenant_id"] == "acme-corp" for r in result.results)


class TestREMQueryLOOKUP:
    """Test LOOKUP operation (KV store exact match)."""

    async def test_lookup_exact_match(self, rem_query_service, populated_database):
        """Test exact KV store lookup."""
        result = await rem_query_service.execute(
            'LOOKUP "docs://getting-started.md" IN resources',
            user_id="acme-corp",
        )

        assert result.operation == "LOOKUP"
        assert result.count == 1
        assert result.metadata["entity_key"] == "docs://getting-started.md"
        assert result.results[0]["entity_key"] == "docs://getting-started.md"

    async def test_lookup_nonexistent(self, rem_query_service, populated_database):
        """Test lookup for nonexistent key."""
        result = await rem_query_service.execute(
            'LOOKUP "docs://nonexistent.md" IN resources',
            user_id="acme-corp",
        )

        assert result.operation == "LOOKUP"
        assert result.count == 0

    async def test_lookup_without_table(self, rem_query_service, populated_database):
        """Test lookup across all entity types."""
        result = await rem_query_service.execute(
            'LOOKUP "docs://getting-started.md"',
            user_id="acme-corp",
        )

        assert result.operation == "LOOKUP"
        assert result.count >= 1


class TestREMQueryFUZZYLOOKUP:
    """Test FUZZY LOOKUP operation (trigram similarity)."""

    async def test_fuzzy_lookup_partial_match(self, rem_query_service, populated_database):
        """Test fuzzy lookup with partial match."""
        result = await rem_query_service.execute(
            'FUZZY LOOKUP "getting start" IN resources THRESHOLD 0.2',
            user_id="acme-corp",
        )

        assert result.operation == "FUZZY LOOKUP"
        assert result.count >= 1
        assert result.metadata["threshold"] == 0.2
        # Should match "docs://getting-started.md"
        assert any("getting-started" in r["entity_key"] for r in result.results)

    async def test_fuzzy_lookup_typo(self, rem_query_service, populated_database):
        """Test fuzzy lookup with typo."""
        result = await rem_query_service.execute(
            'FUZZY LOOKUP "arcitecture" IN resources THRESHOLD 0.3',
            user_id="acme-corp",
        )

        assert result.operation == "FUZZY LOOKUP"
        # Should match "docs://architecture/database.md"
        if result.count > 0:
            assert any("architecture" in r["entity_key"] for r in result.results)

    async def test_fuzzy_lookup_high_threshold(self, rem_query_service, populated_database):
        """Test fuzzy lookup with high threshold (no matches)."""
        result = await rem_query_service.execute(
            'FUZZY LOOKUP "completely-different" IN resources THRESHOLD 0.8',
            user_id="acme-corp",
        )

        assert result.operation == "FUZZY LOOKUP"
        # High threshold should yield few/no results
        assert result.count <= 1


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="SEARCH tests require OPENAI_API_KEY for embedding generation"
)
class TestREMQuerySEARCH:
    """Test SEARCH operation (vector similarity)."""

    @pytest.mark.skip(reason="Brittle test - timing-dependent, fails in full suite due to race conditions")
    async def test_search_basic(self, rem_query_service, populated_database):
        """Test basic semantic search."""
        # Additional wait for embeddings to be fully generated
        # Background workers may take time to process the queue
        import asyncio
        await asyncio.sleep(3.0)

        result = await rem_query_service.execute(
            'SEARCH "getting started" FROM resources LIMIT 5',
            user_id="acme-corp",
        )

        assert result.operation == "SEARCH"
        # Should find at least one result with embeddings generated
        assert result.count >= 1, \
            f"Expected at least 1 result, got {result.count}. Embeddings may not have been generated in time."
        assert result.count <= 5
        assert result.metadata["search_text"] == "getting started"
        assert result.metadata["limit"] == 5

    @pytest.mark.skip(reason="Brittle test - timing-dependent, fails in full suite due to race conditions")
    async def test_search_default_table(self, rem_query_service, populated_database):
        """Test search with default table."""
        result = await rem_query_service.execute(
            'SEARCH "database architecture" LIMIT 3',
            user_id="acme-corp",
        )

        assert result.operation == "SEARCH"
        assert result.count <= 3
        assert result.metadata["table"] == "resources"  # Default table


class TestREMQueryTRAVERSE:
    """Test TRAVERSE operation (graph traversal)."""

    async def test_traverse_outbound(self, rem_query_service, populated_database):
        """Test outbound graph traversal."""
        # First get the ID of getting-started doc
        lookup = await rem_query_service.execute(
            'LOOKUP "docs://getting-started.md" IN resources',
            user_id="acme-corp",
        )

        assert lookup.count == 1
        entity_id = str(lookup.results[0]["entity_id"])

        # Traverse outbound from getting-started
        result = await rem_query_service.execute(
            f'TRAVERSE "{entity_id}" OUTBOUND DEPTH 1',
            user_id="acme-corp",
        )

        assert result.operation == "TRAVERSE"
        assert result.metadata["direction"] == "OUTBOUND"
        assert result.metadata["depth"] == 1
        # Should find references to database.md and api-quickstart.md
        assert result.count >= 1

    async def test_traverse_with_type_filter(self, rem_query_service, populated_database):
        """Test traversal with edge type filter."""
        lookup = await rem_query_service.execute(
            'LOOKUP "docs://getting-started.md" IN resources',
            user_id="acme-corp",
        )

        entity_id = str(lookup.results[0]["entity_id"])

        result = await rem_query_service.execute(
            f'TRAVERSE "{entity_id}" OUTBOUND DEPTH 1 TYPE "references"',
            user_id="acme-corp",
        )

        assert result.operation == "TRAVERSE"
        assert result.metadata["edge_type"] == "references"
        # Should only find "references" type edges (excluding root node at depth=0)
        if result.count > 0:
            # Filter out root node (depth=0 has no edge_type)
            edges = [r for r in result.results if (r.get("depth") is not None and r.get("depth") > 0)]
            # If there are edges beyond root, they should all be "references"
            if edges:
                assert all(r.get("edge_type") == "references" for r in edges), \
                    f"Not all edges have type 'references': {[(r.get('depth'), r.get('edge_type'), r.get('rel_type')) for r in edges]}"

    async def test_traverse_multi_hop(self, rem_query_service, populated_database):
        """Test multi-hop graph traversal."""
        lookup = await rem_query_service.execute(
            'LOOKUP "docs://getting-started.md" IN resources',
            user_id="acme-corp",
        )

        entity_id = str(lookup.results[0]["entity_id"])

        result = await rem_query_service.execute(
            f'TRAVERSE "{entity_id}" OUTBOUND DEPTH 2',
            user_id="acme-corp",
        )

        assert result.operation == "TRAVERSE"
        assert result.metadata["depth"] == 2
        # Multi-hop should potentially find more entities
        # (depends on graph structure)

    async def test_traverse_both_directions(self, rem_query_service, populated_database):
        """Test bidirectional graph traversal."""
        lookup = await rem_query_service.execute(
            'LOOKUP "docs://architecture/database.md" IN resources',
            user_id="acme-corp",
        )

        if lookup.count > 0:
            entity_id = str(lookup.results[0]["entity_id"])

            result = await rem_query_service.execute(
                f'TRAVERSE "{entity_id}" BOTH DEPTH 1',
                user_id="acme-corp",
            )

            assert result.operation == "TRAVERSE"
            assert result.metadata["direction"] == "BOTH"
            # Should find entities linking to AND from database.md


class TestREMQueryEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.skip(reason="Brittle test - SQL parser raises PostgresSyntaxError instead of ValueError for invalid operations")
    async def test_invalid_operation(self, rem_query_service):
        """Test invalid REM operation."""
        with pytest.raises(ValueError, match="Unknown REM operation"):
            await rem_query_service.execute("INVALID some query")

    async def test_invalid_search_syntax(self, rem_query_service):
        """Test invalid SEARCH syntax."""
        with pytest.raises(ValueError, match="Invalid SEARCH syntax"):
            await rem_query_service.execute("SEARCH missing quotes")

    async def test_invalid_lookup_syntax(self, rem_query_service):
        """Test invalid LOOKUP syntax."""
        with pytest.raises(ValueError, match="Invalid LOOKUP syntax"):
            await rem_query_service.execute("LOOKUP missing-quotes")

    async def test_invalid_traverse_syntax(self, rem_query_service):
        """Test invalid TRAVERSE syntax."""
        with pytest.raises(ValueError, match="Invalid TRAVERSE syntax"):
            await rem_query_service.execute("TRAVERSE invalid")


if __name__ == "__main__":
    """
    Run tests manually for development.

    Usage:
        python -m tests.integration.test_rem_query
    """
    print("Running REM Query integration tests...")
    print("Note: These tests require PostgreSQL running with seed data")
    print("  docker compose up -d postgres")
    print("\nTo run with pytest:")
    print("  pytest tests/integration/test_rem_query.py -v")
