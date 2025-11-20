"""Test PDF processing pipeline."""

import asyncio
from pathlib import Path

from loguru import logger

from rem.services.content import ContentService
from rem.services.postgres import PostgresService
from rem.services.repositories import FileRepository, ResourceRepository
from rem.settings import settings


async def test_process_pdf():
    """Test processing a PDF file."""
    # PDF to test
    pdf_path = Path("/Users/sirsh/Downloads/01_stock_hotel.pdf")

    logger.info(f"Testing PDF processing: {pdf_path}")

    # Setup database
    db = PostgresService(
        connection_string=settings.postgres.connection_string,
        pool_size=5,
    )
    await db.connect()

    try:
        # Create repositories
        file_repo = FileRepository(db)
        resource_repo = ResourceRepository(db)

        # Create content service
        service = ContentService(file_repo=file_repo, resource_repo=resource_repo)

        # Process and save (with tenant_id)
        result = await service.process_and_save(str(pdf_path), user_id="test-user")

        logger.info(f"Processing complete:")
        logger.info(f"  File: {result['file']['name']}")
        logger.info(f"  Chunks: {result['chunk_count']}")
        logger.info(f"  Status: {result['status']}")

        # Wait for embedding worker to process queue
        logger.info("Waiting for embeddings to be generated...")
        await asyncio.sleep(2)

    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(test_process_pdf())
