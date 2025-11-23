"""
Integration tests for batch upsert with KV store population.

Tests:
1. Load seed data from YAML
2. Batch upsert to PostgreSQL
3. Verify KV store population via triggers
4. Test deterministic ID generation with composite keys
5. Verify embedding table structure (generation stubbed)

Requires:
- Running PostgreSQL instance (docker compose up -d postgres)
- Migrations applied (001_install.sql, 002_install_models.sql)
"""

import asyncio
from pathlib import Path

import pytest
import yaml

from rem.models.entities import Resource
from rem.services.postgres import PostgresService, Repository
from rem.utils.model_helpers import get_entity_key_field, get_embeddable_fields


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
    """
    Create PostgresService instance.
    """
    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


class TestBatchUpsertIntegration:
    """Integration tests for batch upsert functionality."""

    async def test_load_seed_data(self, resources_seed_data):
        """Test loading seed data from YAML."""
        assert len(resources_seed_data) == 5
        assert resources_seed_data[0]["name"] == "docs://getting-started.md"
        assert resources_seed_data[0]["tenant_id"] == "acme-corp"
        assert "content" in resources_seed_data[0]

    async def test_batch_upsert_resources(
        self, postgres_service, resources_seed_data
    ):
        """Test batch upserting resources with KV store population."""
        # Convert YAML data to Resource models
        resources = []
        for data in resources_seed_data:
            # Add ordinal if not present (for single-chunk resources)
            if "ordinal" not in data:
                data["ordinal"] = 0

            # Parse timestamp (convert to timezone-naive to match CoreModel)
            if "timestamp" in data and isinstance(data["timestamp"], str):
                from datetime import datetime

                data["timestamp"] = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                ).replace(tzinfo=None)

            resource = Resource(**data)
            resources.append(resource)

        # Get entity key field and embeddable fields
        entity_key_field = get_entity_key_field(Resource)  # Should be "name"
        embeddable_fields = get_embeddable_fields(Resource)  # Should include "content"

        assert entity_key_field == "name"
        assert "content" in embeddable_fields

        # Batch upsert using Repository pattern
        repo = Repository(Resource, "resources", db=postgres_service)
        upserted = await repo.upsert(resources)

        # Verify results (Repository.upsert returns the records, not a dict)
        assert len(upserted) == 5

        # Verify all resources were upserted (have IDs)
        for resource in upserted:
            assert resource.id is not None

    async def test_deterministic_id_generation(self, resources_seed_data):
        """Test that resources with same URI + ordinal get same ID."""
        from rem.utils.batch_ops import prepare_record_for_upsert

        # Create two resources with same URI + ordinal but different content
        data1 = resources_seed_data[0].copy()
        data1["ordinal"] = 0
        data1["content"] = "Version 1 content"

        data2 = resources_seed_data[0].copy()
        data2["ordinal"] = 0
        data2["content"] = "Version 2 content (updated)"

        resource1 = Resource(**data1)
        resource2 = Resource(**data2)

        # Prepare both for upsert
        prepared1 = prepare_record_for_upsert(resource1, Resource, entity_key_field="uri")
        prepared2 = prepare_record_for_upsert(resource2, Resource, entity_key_field="uri")

        # IDs should be the same (deterministic)
        assert prepared1["id"] == prepared2["id"]

        # Now test with different ordinal
        data3 = resources_seed_data[0].copy()
        data3["ordinal"] = 1  # Different chunk
        resource3 = Resource(**data3)
        prepared3 = prepare_record_for_upsert(resource3, Resource, entity_key_field="uri")

        # ID should be different (different ordinal)
        assert prepared1["id"] != prepared3["id"]

    @pytest.mark.skip("Requires PostgreSQL connection implementation")
    async def test_kv_store_lookup(self, postgres_service):
        """Test that KV store is populated via triggers and supports fuzzy lookup."""
        # TODO: After upserting resources, verify KV store contents
        # SELECT * FROM kv_store WHERE tenant_id = 'acme-corp'
        # Should have 5 entries with entity_type = 'resources'

        # TODO: Test fuzzy lookup
        # SELECT * FROM rem_fuzzy('getting-started', 'acme-corp', 0.3, 10)
        # Should match "getting-started-guide"
        pass

    @pytest.mark.skip("Requires PostgreSQL connection implementation")
    async def test_embedding_table_structure(self, postgres_service):
        """Test that embeddings table exists with correct schema."""
        # TODO: Query schema
        # SELECT column_name, data_type FROM information_schema.columns
        # WHERE table_name = 'embeddings_resources'

        # Expected columns:
        # - id (uuid)
        # - entity_id (uuid, FK to resources)
        # - field_name (varchar) - should be "content"
        # - provider (varchar) - "openai"
        # - model (varchar) - "text-embedding-3-small"
        # - embedding (vector(1536))
        # - created_at, updated_at (timestamp)

        # TODO: Verify unique constraint on (entity_id, field_name, provider)
        pass


class TestSeedDataLoaderUtil:
    """Test utility for loading and converting seed data."""

    def test_load_resources_yaml(self, resources_seed_data):
        """Test loading resources from YAML."""
        assert isinstance(resources_seed_data, list)
        assert len(resources_seed_data) > 0

        # Check first resource structure
        first = resources_seed_data[0]
        assert "name" in first
        assert "content" in first
        assert "tenant_id" in first
        assert "user_id" in first

    def test_convert_to_pydantic_models(self, resources_seed_data):
        """Test converting YAML data to Pydantic models."""
        from datetime import datetime

        resources = []
        for data in resources_seed_data:
            # Add defaults
            if "ordinal" not in data:
                data["ordinal"] = 0

            # Parse timestamp (convert to timezone-naive to match CoreModel)
            if "timestamp" in data and isinstance(data["timestamp"], str):
                data["timestamp"] = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                ).replace(tzinfo=None)

            resource = Resource(**data)
            resources.append(resource)

        assert len(resources) == len(resources_seed_data)
        assert all(isinstance(r, Resource) for r in resources)

        # Check first resource
        first = resources[0]
        assert first.name == "docs://getting-started.md"
        assert first.tenant_id == "acme-corp"
        assert first.ordinal == 0


if __name__ == "__main__":
    """
    Run tests manually for development.

    Usage:
        python -m tests.integration.test_batch_upsert
    """
    print("Running batch upsert integration tests...")

    # Test loading seed data
    seed_path = Path(__file__).parent.parent / "data" / "seed"
    yaml_file = seed_path / "resources.yaml"

    with open(yaml_file) as f:
        data = yaml.safe_load(f)

    resources_data = data.get("resources", [])
    print(f"✓ Loaded {len(resources_data)} resources from YAML")

    # Test converting to Pydantic models
    from datetime import datetime

    resources = []
    for item in resources_data:
        if "ordinal" not in item:
            item["ordinal"] = 0
        if "timestamp" in item and isinstance(item["timestamp"], str):
            item["timestamp"] = datetime.fromisoformat(
                item["timestamp"].replace("Z", "+00:00")
            ).replace(tzinfo=None)

        resource = Resource(**item)
        resources.append(resource)

    print(f"✓ Converted to {len(resources)} Resource models")

    # Test deterministic ID generation
    from rem.utils.batch_ops import prepare_record_for_upsert

    resource1 = resources[0]
    prepared = prepare_record_for_upsert(resource1, Resource, entity_key_field="uri")

    print(f"✓ Generated deterministic ID: {prepared['id']}")
    print(f"  Based on: uri={prepared.get('uri')}, ordinal={prepared.get('ordinal')}")

    # Test metadata extraction
    from rem.utils.model_helpers import get_model_metadata

    metadata = get_model_metadata(Resource)
    print(f"✓ Resource model metadata:")
    print(f"  table_name: {metadata['table_name']}")
    print(f"  entity_key_field: {metadata['entity_key_field']}")
    print(f"  embeddable_fields: {metadata['embeddable_fields']}")

    print("\n✓ All manual tests passed!")
    print("\nTo run integration tests with PostgreSQL:")
    print("  1. docker compose up -d postgres")
    print("  2. pytest tests/integration/test_batch_upsert.py")
