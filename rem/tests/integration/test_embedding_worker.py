"""
Integration tests for background embedding worker.

Tests:
1. Start/stop embedding worker
2. Queue embedding tasks
3. Worker processes tasks and generates embeddings
4. Embeddings are upserted to database
5. Batch processing and timeout handling

Requires:
- Running PostgreSQL instance (docker compose up -d postgres)
"""

import asyncio
from pathlib import Path

import pytest
import yaml

from rem.models.entities import Resource
from rem.services.embeddings import EmbeddingWorker
from rem.services.postgres import PostgresService
from rem.utils.model_helpers import get_embeddable_fields


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
    """Create PostgresService instance without embedding worker."""
    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def embedding_worker(postgres_service) -> EmbeddingWorker:
    """Create and start EmbeddingWorker."""
    worker = EmbeddingWorker(
        postgres_service=postgres_service,
        num_workers=2,
        batch_size=3,
        batch_timeout=0.5,
    )
    await worker.start()
    yield worker
    await worker.stop()


class TestEmbeddingWorker:
    """Integration tests for EmbeddingWorker."""

    async def test_worker_start_stop(self, postgres_service):
        """Test starting and stopping worker."""
        worker = EmbeddingWorker(postgres_service=postgres_service, num_workers=2)

        assert not worker.running
        assert len(worker.workers) == 0

        await worker.start()
        assert worker.running
        assert len(worker.workers) == 2

        await worker.stop()
        assert not worker.running
        assert len(worker.workers) == 0

    async def test_queue_embedding_task(self, embedding_worker):
        """Test queuing embedding task."""
        from rem.services.embeddings import EmbeddingTask

        task = EmbeddingTask(
            task_id="test-1",
            entity_id="123e4567-e89b-12d3-a456-426614174000",
            table_name="resources",
            field_name="content",
            content="This is test content for embedding",
            provider="openai",
            model="text-embedding-3-small",
        )

        initial_size = embedding_worker.task_queue.qsize()
        await embedding_worker.queue_task(task)

        # Task should be queued
        assert embedding_worker.task_queue.qsize() == initial_size + 1

    async def test_background_embedding_generation(
        self, postgres_service, resources_seed_data
    ):
        """Test end-to-end background embedding generation."""
        # Create worker with short timeout for testing
        worker = EmbeddingWorker(
            postgres_service=postgres_service,
            num_workers=1,
            batch_size=2,
            batch_timeout=0.5,
        )
        await worker.start()

        try:
            # Upsert resources with embedding worker
            postgres_service.embedding_worker = worker

            # Convert YAML to Resource models
            resources = []
            for data in resources_seed_data[:2]:  # Just 2 for faster test
                if "ordinal" not in data:
                    data["ordinal"] = 0
                if "timestamp" in data and isinstance(data["timestamp"], str):
                    from datetime import datetime

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
            assert len(upserted) == 2

            # Wait for worker to process tasks
            await asyncio.sleep(2)

            # Verify embeddings were created for our specific resources
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

            # Should have 2 embeddings (one per resource)
            assert len(embeddings) == 2

            # Verify embedding properties
            for emb in embeddings:
                assert emb["field_name"] == "content"
                assert emb["provider"] == "openai"
                assert emb["model"] == "text-embedding-3-small"
                assert emb["dims"] == 1536  # text-embedding-3-small dimension

        finally:
            await worker.stop()

    async def test_batch_processing(self, postgres_service):
        """Test that worker batches tasks efficiently."""
        from uuid import uuid4
        from rem.models.entities import Resource

        worker = EmbeddingWorker(
            postgres_service=postgres_service,
            num_workers=1,
            batch_size=3,
            batch_timeout=1.0,
        )
        await worker.start()

        try:
            from rem.services.embeddings import EmbeddingTask

            # First create the resource records (required for FK constraint)
            resource_ids = []
            for i in range(5):
                resource_id = str(uuid4())
                resource_ids.append(resource_id)
                await postgres_service.execute(
                    "INSERT INTO resources (id, name, uri, content, tenant_id) VALUES ($1, $2, $3, $4, $5)",
                    [resource_id, f"test-resource-{i}", f"test://resource-{i}", f"Test content {i}", "test-tenant"]
                )

            # Queue 5 tasks
            for i, resource_id in enumerate(resource_ids):
                task = EmbeddingTask(
                    task_id=f"test-{i}",
                    entity_id=resource_id,
                    table_name="resources",
                    field_name="content",
                    content=f"Test content {i}",
                )
                await worker.queue_task(task)

            # Wait for processing
            await asyncio.sleep(2)

            # All tasks should be processed
            assert worker.task_queue.qsize() == 0

        finally:
            await worker.stop()


class TestBatchUpsertWithWorker:
    """Test batch_upsert integration with embedding worker."""

    async def test_upsert_without_worker(self, postgres_service, resources_seed_data):
        """Test that upsert works without embedding worker (backward compat)."""
        # Clear embedding worker to test backward compatibility
        postgres_service.embedding_worker = None
        assert postgres_service.embedding_worker is None

        # Convert YAML to Resource models
        resources = []
        for data in resources_seed_data[:1]:
            if "ordinal" not in data:
                data["ordinal"] = 0
            if "timestamp" in data and isinstance(data["timestamp"], str):
                from datetime import datetime

                data["timestamp"] = datetime.fromisoformat(
                    data["timestamp"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            resource = Resource(**data)
            resources.append(resource)

        # Batch upsert using Repository pattern (no embeddings worker)
        from rem.services.postgres import Repository
        repo = Repository(Resource, "resources", db=postgres_service)
        upserted = await repo.upsert(resources)

        # Should complete successfully
        assert len(upserted) == 1


if __name__ == "__main__":
    """
    Run tests manually for development.

    Usage:
        python -m tests.integration.test_embedding_worker
    """
    print("Running embedding worker integration tests...")
    print("Note: These tests require PostgreSQL running")
    print("  docker compose up -d postgres")
    print("\nTo run with pytest:")
    print("  pytest tests/integration/test_embedding_worker.py -v")
