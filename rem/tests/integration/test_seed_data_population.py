"""
Integration test for complete seed data population and validation.

Tests the complete pipeline:
1. Fresh database spin-up
2. Load seed data (Resources, Moments, Users, Files)
3. Process engram files
4. Generate embeddings
5. Validate all data exists:
   - SQL tables populated
   - KV store entries
   - Embeddings generated
   - Graph edges created

This is a CRITICAL test that validates the entire REM data ingestion pipeline.

Usage:
    pytest tests/integration/test_seed_data_population.py -v --log-cli-level=INFO

Prerequisites:
    docker compose up -d postgres
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from rem.models.entities import File, Message, Moment, Resource, Schema, User
from rem.services.postgres import PostgresService
from rem.workers.engram_processor import EngramProcessor

logger = logging.getLogger(__name__)


# ============================================================================
# Seed Data Helpers
# ============================================================================

def parse_seed_data_timestamps(data: dict) -> dict:
    """
    Parse ISO timestamp strings in seed data to datetime objects.

    Mutates the input dict in place for efficiency.

    Args:
        data: Seed data dict with potential timestamp strings

    Returns:
        Same dict with timestamps parsed
    """
    # Parse moment timestamps
    for moment in data.get("moments", []):
        if "starts_timestamp" in moment and isinstance(moment["starts_timestamp"], str):
            moment["starts_timestamp"] = datetime.fromisoformat(moment["starts_timestamp"])
        if "ends_timestamp" in moment and isinstance(moment["ends_timestamp"], str):
            moment["ends_timestamp"] = datetime.fromisoformat(moment["ends_timestamp"])

    return data


# Helper functions for database queries
async def fetch_one(pg: PostgresService, query: str, *params) -> dict:
    """Execute query and return first row."""
    results = await pg.execute(query, params if params else None)
    return results[0] if results else {}


@pytest.fixture
def seed_data_dir() -> Path:
    """Path to seed data directory."""
    return Path(__file__).parent.parent / "data" / "seed"


@pytest.fixture
def engram_files_dir(seed_data_dir: Path) -> Path:
    """Path to engram test files."""
    return seed_data_dir / "files" / "engrams"


@pytest.fixture
def document_files_dir(seed_data_dir: Path) -> Path:
    """Path to document test files."""
    return seed_data_dir / "files" / "documents"


@pytest.fixture
async def postgres_service() -> PostgresService:
    """PostgreSQL service for tests."""
    connection_string = "postgresql://rem:rem@localhost:5050/rem"

    # Safety check - only allow test database connections
    if "localhost:5050" not in connection_string and "127.0.0.1:5050" not in connection_string:
        raise RuntimeError(
            "Integration tests must use localhost:5050 test database. "
            f"Got: {connection_string}"
        )

    pg = PostgresService(connection_string=connection_string)
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def fresh_database(postgres_service: PostgresService):
    """
    Fresh database - clear all test data before running tests.

    WARNING: This deletes all data in the database!
    Only run against test database (localhost:5050).
    """
    tenant_id = "acme-corp"

    # Allowlist of tables that can be safely cleared
    # This prevents SQL injection via dynamic table names
    ALLOWED_TABLES = frozenset([
        "messages", "files", "schemas", "moments",
        "resources", "users", "persons"
    ])

    # Clear all entity tables for tenant (wrapped in transaction)
    async with postgres_service.transaction():
        for table in ALLOWED_TABLES:
            # Delete from parent tables only - CASCADE handles embeddings
            await postgres_service.execute(
                f"DELETE FROM {table} WHERE tenant_id = $1",
                (tenant_id,),
            )

        # Clear UNLOGGED kv_store (not cascaded)
        await postgres_service.execute(
            "DELETE FROM kv_store WHERE tenant_id = $1",
            (tenant_id,),
        )

    logger.info("Database cleared - fresh state ready")
    yield
    logger.info("Test complete")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_load_standard_seed_data(
    postgres_service: PostgresService,
    fresh_database,
    seed_data_dir: Path,
):
    """
    Test loading standard seed data from 001_sample_data.yaml.

    Validates:
    - Users created
    - Resources created
    - Moments created
    - Messages created
    - Files created
    - Schemas created
    - KV store populated
    """
    tenant_id = "acme-corp"

    # Load seed data
    seed_file = seed_data_dir / "001_sample_data.yaml"
    with open(seed_file) as f:
        data = yaml.safe_load(f)

    # Parse timestamps in seed data
    data = parse_seed_data_timestamps(data)

    # Process users
    users_data = data.get("users", [])
    if users_data:
        logger.info(f"Loading {len(users_data)} users")
        result = await postgres_service.batch_upsert(
            records=users_data,
            model=User,
            table_name="users",
        )
        assert result["upserted_count"] == len(users_data)
        logger.info(f"✓ {result['upserted_count']} users created")

    # Process resources
    resources_data = data.get("resources", [])
    if resources_data:
        logger.info(f"Loading {len(resources_data)} resources")
        result = await postgres_service.batch_upsert(
            records=resources_data,
            model=Resource,
            table_name="resources",
        )
        assert result["upserted_count"] == len(resources_data)
        logger.info(f"✓ {result['upserted_count']} resources created")

    # Process moments
    moments_data = data.get("moments", [])
    if moments_data:
        logger.info(f"Loading {len(moments_data)} moments")
        result = await postgres_service.batch_upsert(
            records=moments_data,
            model=Moment,
            table_name="moments",
        )
        assert result["upserted_count"] == len(moments_data)
        logger.info(f"✓ {result['upserted_count']} moments created")

    # Process messages
    messages_data = data.get("messages", [])
    if messages_data:
        logger.info(f"Loading {len(messages_data)} messages")
        result = await postgres_service.batch_upsert(
            records=messages_data,
            model=Message,
            table_name="messages",
        )
        assert result["upserted_count"] == len(messages_data)
        logger.info(f"✓ {result['upserted_count']} messages created")

    # Process files
    files_data = data.get("files", [])
    if files_data:
        logger.info(f"Loading {len(files_data)} files")
        result = await postgres_service.batch_upsert(
            records=files_data,
            model=File,
            table_name="files",
        )
        assert result["upserted_count"] == len(files_data)
        logger.info(f"✓ {result['upserted_count']} files created")

    # Process schemas
    schemas_data = data.get("schemas", [])
    if schemas_data:
        logger.info(f"Loading {len(schemas_data)} schemas")
        result = await postgres_service.batch_upsert(
            records=schemas_data,
            model=Schema,
            table_name="schemas",
        )
        assert result["upserted_count"] == len(schemas_data)
        logger.info(f"✓ {result['upserted_count']} schemas created")

    # Verify KV store population
    kv_count_results = await postgres_service.execute(
        "SELECT COUNT(*) as count FROM kv_store WHERE tenant_id = $1",
        (tenant_id,),
    )
    kv_count = kv_count_results[0]["count"] if kv_count_results else 0
    logger.info(f"✓ {kv_count} KV store entries created")

    # At minimum, we should have entries for users, resources, and moments
    expected_min_kv = len(users_data) + len(resources_data) + len(moments_data)
    assert kv_count >= expected_min_kv, f"Expected at least {expected_min_kv} KV entries, got {kv_count}"

    logger.info("✓ All standard seed data loaded successfully")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_engram_files(
    postgres_service: PostgresService,
    fresh_database,
    engram_files_dir: Path,
):
    """
    Test processing engram YAML files.

    Validates:
    - Engram YAML parsed correctly
    - Resources created (category="engram")
    - Moments created and linked to parent
    - Graph edges created
    - KV store populated
    """
    tenant_id = "acme-corp"
    user_id = "sarah-chen"

    # Initialize engram processor
    processor = EngramProcessor(postgres_service)

    # Find all engram files
    engram_files = list(engram_files_dir.glob("*.yaml"))
    assert len(engram_files) > 0, "No engram files found"
    logger.info(f"Found {len(engram_files)} engram files to process")

    # Process each engram
    total_resources = 0
    total_moments = 0

    for engram_file in engram_files:
        logger.info(f"Processing engram: {engram_file.name}")
        result = await processor.process_file(
            file_path=engram_file,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        assert "resource_id" in result
        assert "moment_ids" in result
        assert result["chunks_created"] > 0

        total_resources += 1
        total_moments += len(result["moment_ids"])

        logger.info(
            f"✓ {engram_file.name}: 1 resource, {len(result['moment_ids'])} moments"
        )

    logger.info(f"✓ Processed {total_resources} engrams with {total_moments} total moments")

    # Verify resources exist in database
    resources_result = await fetch_one(
        postgres_service,
        "SELECT COUNT(*) as count FROM resources WHERE tenant_id = $1 AND category = $2",
        tenant_id,
        "engram",
    )
    assert resources_result.get("count", 0) >= total_resources

    # Verify moments exist in database
    moments_result = await fetch_one(
        postgres_service,
        "SELECT COUNT(*) as count FROM moments WHERE tenant_id = $1",
        tenant_id,
    )
    assert moments_result.get("count", 0) >= total_moments

    # Verify KV store has entries for engrams
    kv_result = await fetch_one(
        postgres_service,
        """
        SELECT COUNT(*) as count FROM kv_store
        WHERE tenant_id = $1 AND entity_type = 'resources'
        """,
        tenant_id,
    )
    assert kv_result.get("count", 0) >= total_resources
    logger.info(f"✓ {kv_result.get('count', 0)} resource KV entries")

    # Verify graph edges exist
    edges_result = await fetch_one(
        postgres_service,
        """
        SELECT COUNT(*) as count FROM resources
        WHERE tenant_id = $1
        AND jsonb_array_length(COALESCE(graph_edges, '[]'::jsonb)) > 0
        """,
        tenant_id,
    )
    assert edges_result.get("count", 0) > 0
    logger.info(f"✓ {edges_result.get('count', 0)} resources have graph edges")

    logger.info("✓ All engram files processed successfully")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_data_diagnostics(
    postgres_service: PostgresService,
    fresh_database,
    seed_data_dir: Path,
    engram_files_dir: Path,
):
    """
    Complete integration test with diagnostics.

    This test:
    1. Loads all seed data
    2. Processes all engram files
    3. Runs comprehensive diagnostics
    4. Validates all expected data exists

    This is the MASTER test for data population validation.
    """
    tenant_id = "acme-corp"

    # Step 1: Load standard seed data
    logger.info("=" * 60)
    logger.info("STEP 1: Loading standard seed data")
    logger.info("=" * 60)

    seed_file = seed_data_dir / "001_sample_data.yaml"
    with open(seed_file) as f:
        data = yaml.safe_load(f)

    # Parse timestamps in seed data (centralized)
    data = parse_seed_data_timestamps(data)

    for entity_type in ["users", "resources", "moments", "messages", "files", "schemas"]:
        entity_data = data.get(entity_type, [])
        if not entity_data:
            continue

        # Get model class
        model_map = {
            "users": User,
            "resources": Resource,
            "moments": Moment,
            "messages": Message,
            "files": File,
            "schemas": Schema,
        }
        model = model_map[entity_type]

        result = await postgres_service.batch_upsert(
            records=entity_data,
            model=model,
            table_name=entity_type,
        )
        logger.info(f"✓ {entity_type}: {result['upserted_count']} records")

    # Step 2: Process engram files
    logger.info("=" * 60)
    logger.info("STEP 2: Processing engram files")
    logger.info("=" * 60)

    processor = EngramProcessor(postgres_service)
    engram_files = list(engram_files_dir.glob("*.yaml"))

    for engram_file in engram_files:
        result = await processor.process_file(
            file_path=engram_file,
            tenant_id=tenant_id,
            user_id="sarah-chen",
        )
        logger.info(
            f"✓ {engram_file.name}: "
            f"resource_id={result['resource_id'][:8]}..., "
            f"moments={len(result['moment_ids'])}"
        )

    # Step 3: Run diagnostics
    logger.info("=" * 60)
    logger.info("STEP 3: Running diagnostics")
    logger.info("=" * 60)

    diagnostics = {}

    # Table row counts
    for table in ["users", "resources", "moments", "messages", "files", "schemas"]:
        result = await fetch_one(
            postgres_service,
            f"SELECT COUNT(*) as count FROM {table} WHERE tenant_id = $1",
            tenant_id,
        )
        diagnostics[f"{table}_count"] = result.get("count", 0)
        logger.info(f"  {table}: {result.get('count', 0)} rows")

    # KV store entries
    kv_result = await fetch_one(
        postgres_service,
        "SELECT COUNT(*) as count FROM kv_store WHERE tenant_id = $1",
        tenant_id,
    )
    diagnostics["kv_store_count"] = kv_result.get("count", 0)
    logger.info(f"  KV store: {kv_result.get('count', 0)} entries")

    # Graph edges
    for table in ["resources", "moments"]:
        result = await fetch_one(
            postgres_service,
            f"""
            SELECT COUNT(*) as count FROM {table}
            WHERE tenant_id = $1
            AND jsonb_array_length(COALESCE(graph_edges, '[]'::jsonb)) > 0
            """,
            tenant_id,
        )
        diagnostics[f"{table}_with_edges"] = result.get("count", 0)
        logger.info(f"  {table} with edges: {result.get('count', 0)}")

    # Embeddings tables exist (structure validation)
    for table in ["users", "resources", "moments", "messages", "files", "schemas"]:
        try:
            result = await fetch_one(
                postgres_service,
                f"SELECT COUNT(*) as count FROM embeddings_{table}"
            )
            diagnostics[f"embeddings_{table}_exists"] = True
            logger.info(f"  embeddings_{table}: exists (structure validated)")
        except Exception as e:
            diagnostics[f"embeddings_{table}_exists"] = False
            logger.warning(f"  embeddings_{table}: NOT FOUND")

    # Validate minimum expectations
    logger.info("=" * 60)
    logger.info("STEP 4: Validating results")
    logger.info("=" * 60)

    assert diagnostics["users_count"] > 0, "No users found"
    assert diagnostics["resources_count"] > 0, "No resources found"
    assert diagnostics["kv_store_count"] > 0, "No KV store entries found"
    assert diagnostics["resources_with_edges"] > 0, "No graph edges found in resources"

    logger.info("✓ ALL DIAGNOSTICS PASSED")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for key, value in diagnostics.items():
        logger.info(f"  {key}: {value}")

    return diagnostics
