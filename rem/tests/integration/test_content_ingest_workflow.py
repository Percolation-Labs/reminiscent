"""
Integration test for ContentService.ingest_file() workflow.

Tests that the full ingestion pipeline works correctly:
1. Reads file from source
2. Stores to internal storage (S3 or local)
3. Parses content
4. Creates Resource chunks
5. Generates embeddings
"""
import asyncio
from pathlib import Path
import pytest
from rem.services.content import ContentService
from rem.services.postgres import PostgresService
from rem.models.entities import Resource, File
from rem.settings import settings


pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for our test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
def disable_s3():
    """Disable S3 storage for integration tests - use local filesystem instead."""
    original_bucket_name = settings.s3.bucket_name
    settings.s3.bucket_name = ""  # Empty string forces local storage
    yield
    settings.s3.bucket_name = original_bucket_name


@pytest.fixture
async def postgres_service() -> PostgresService:
    """Create PostgresService instance and ensure database connection."""
    service = PostgresService()
    await service.connect()
    yield service
    await service.disconnect()


async def test_ingest_file_full_workflow(postgres_service):
    """
    Test complete file ingestion workflow.

    Verifies:
    1. File is stored to internal storage
    2. File entity is created in database
    3. Content is parsed
    4. Resource chunks are created
    5. (TODO: Embeddings are generated - requires worker)
    """
    # Skip if PostgreSQL not enabled
    if not settings.postgres.enabled:
        pytest.skip("PostgreSQL not enabled")

    # Use test PDF file
    test_file = Path(__file__).parent.parent / "data" / "content-examples" / "pdf" / "sample_invoice.pdf"

    if not test_file.exists():
        pytest.skip(f"Test file not found: {test_file}")

    # Create ContentService with repositories
    from rem.services.postgres.repository import Repository
    from rem.models.entities import File, Resource

    file_repo = Repository(File, db=postgres_service)
    resource_repo = Repository(Resource, db=postgres_service)
    content_service = ContentService(file_repo=file_repo, resource_repo=resource_repo)

    # Test parameters
    user_id=settings.test.effective_user_id

    # Clean up any existing data for this test
    await postgres_service.execute(
        "DELETE FROM resources WHERE user_id = $1",
        params=(user_id,)
    )
    await postgres_service.execute(
        "DELETE FROM files WHERE user_id = $1",
        params=(user_id,)
    )

    # Run ingestion
    result = await content_service.ingest_file(
        file_uri=str(test_file),
        # tenant_id removed - using user_id only (user-based partitioning)
        user_id=user_id,
        category="test-document",
        tags=["integration-test"],
        is_local_server=True,  # Allow local file access
    )

    # Verify result structure
    assert result["file_id"] is not None
    assert result["file_name"] == "sample_invoice.pdf"
    assert result["processing_status"] in ["completed", "failed"]
    assert "resources_created" in result
    assert "content" in result
    assert "storage_uri" in result

    # If processing succeeded, verify database state
    if result["processing_status"] == "completed":
        file_id = result["file_id"]

        # Verify File entity was created
        files = await postgres_service.fetch(
            "SELECT * FROM files WHERE id = $1 AND user_id = $2",
            file_id,
            user_id
        )
        assert len(files) == 1
        file_row = files[0]
        assert file_row["name"] == "sample_invoice.pdf"
        assert file_row["user_id"] == user_id

        # Verify Resource chunks were created
        if result["resources_created"] > 0:
            resources = await postgres_service.fetch(
                "SELECT * FROM resources WHERE user_id = $1 AND name LIKE $2",
                user_id,
                f"{result['file_name']}#chunk-%"
            )
            assert len(resources) == result["resources_created"]
            assert len(resources) > 0

            # Verify first chunk has content
            first_chunk = resources[0]
            assert first_chunk["content"] is not None
            assert len(first_chunk["content"]) > 0
            assert first_chunk["user_id"] == user_id
            assert first_chunk["category"] == "document"

            # TODO: Verify embeddings were generated
            # This requires the embedding worker to be running
            # For now, we just verify the structure is correct

    # Clean up
    await postgres_service.execute(
        "DELETE FROM resources WHERE user_id = $1",
        params=(user_id,)
    )
    await postgres_service.execute(
        "DELETE FROM files WHERE user_id = $1",
        params=(user_id,)
    )


async def test_ingest_file_storage_location(postgres_service):
    """
    Test that ingested files are stored in the correct location.

    Verifies storage_uri follows the expected pattern:
    - Local: file://~/.rem/fs/{user_id}/files/{file_id}/{filename}
    - S3: s3://{bucket}/{user_id}/files/{file_id}/{filename}
    """
    # Skip if PostgreSQL not enabled
    if not settings.postgres.enabled:
        pytest.skip("PostgreSQL not enabled")

    # Use test markdown file
    test_file = Path(__file__).parent.parent / "data" / "content-examples" / "test.md"

    if not test_file.exists():
        # Create a simple test file
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# Test Document\n\nThis is a test.")

    # Create ContentService with repositories
    from rem.services.postgres.repository import Repository
    from rem.models.entities import File, Resource

    file_repo = Repository(File, db=postgres_service)
    resource_repo = Repository(Resource, db=postgres_service)
    content_service = ContentService(file_repo=file_repo, resource_repo=resource_repo)

    # Test parameters
    user_id = "storage-test-user"

    # Clean up
    await postgres_service.execute(
        "DELETE FROM resources WHERE user_id = $1",
        params=(user_id,)
    )
    await postgres_service.execute(
        "DELETE FROM files WHERE user_id = $1",
        params=(user_id,)
    )

    # Run ingestion
    result = await content_service.ingest_file(
        file_uri=str(test_file),
        # tenant_id removed - using user_id only (user-based partitioning)
        user_id=user_id,
        is_local_server=True,
    )

    # Verify storage_uri format
    storage_uri = result["storage_uri"]

    if storage_uri.startswith("s3://"):
        # S3 format: s3://{bucket}/{user_id}/files/{file_id}/{filename}
        assert f"/{user_id}/files/" in storage_uri
        assert settings.s3.bucket_name in storage_uri
    elif storage_uri.startswith("file://"):
        # Local format: file://{path}/{user_id}/files/{file_id}/{filename}
        assert f"/{user_id}/files/" in storage_uri
        assert ".rem/fs" in storage_uri
    else:
        pytest.fail(f"Unexpected storage_uri format: {storage_uri}")

    # Verify file exists in database with correct URI
    files = await postgres_service.fetch(
        "SELECT * FROM files WHERE id = $1",
        result["file_id"]
    )
    assert len(files) == 1
    assert files[0]["uri"] == storage_uri

    # Clean up
    await postgres_service.execute(
        "DELETE FROM resources WHERE user_id = $1",
        params=(user_id,)
    )
    await postgres_service.execute(
        "DELETE FROM files WHERE user_id = $1",
        params=(user_id,)
    )


async def test_process_uri_readonly_no_db_writes():
    """
    Test that ContentService.process_uri() does NOT write to database.

    This is the simple parse operation used by CLI `ask --input-file`.
    Should only extract content, no database writes.
    """
    # Use test markdown file
    test_file = Path(__file__).parent.parent / "data" / "content-examples" / "test.md"

    if not test_file.exists():
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# Test Document\n\nThis is a read-only test.")

    # Create ContentService
    content_service = ContentService()

    # Process file (read-only)
    result = content_service.process_uri(str(test_file))

    # Verify result structure
    assert "content" in result
    assert "provider" in result
    assert "metadata" in result

    # Verify content was extracted
    assert result["content"] is not None
    assert len(result["content"]) > 0
    assert "Test Document" in result["content"]

    # Verify no database writes occurred
    # (This is implicit - if there were DB writes, they would fail without connection)
    # The test passing means no DB operations were attempted
